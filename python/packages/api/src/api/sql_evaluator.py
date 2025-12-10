"""
SQL Evaluation and Calculator Utilities for API package.

Phase 3: Evaluation LLM - Validates SQL results for correctness
Phase 4: Calculator - Safe expression evaluation for numeric accuracy

Works with both local (SQLite, DuckDB) and Azure SQL databases.
"""

import ast
import json
import logging
import operator
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# =============================================================================
# Phase 4: Safe Calculator
# =============================================================================

class SafeCalculator:
    """
    Safe mathematical expression evaluator without using eval().
    
    Supports: +, -, *, /, **, %, parentheses, and common math functions.
    """
    
    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }
    
    FUNCTIONS = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'avg': lambda *args: sum(args) / len(args) if args else 0,
    }
    
    def __init__(self, precision: int = 10):
        self.precision = precision
    
    def evaluate(self, expression: str, variables: Optional[Dict[str, float]] = None) -> Union[float, int, None]:
        """Safely evaluate a mathematical expression."""
        if not expression or not isinstance(expression, str):
            return None
            
        try:
            expr = expression.strip()
            
            if variables:
                for name, value in variables.items():
                    expr = re.sub(rf'\b{name}\b', str(value), expr)
            
            tree = ast.parse(expr, mode='eval')
            result = self._eval_node(tree.body)
            
            if isinstance(result, float):
                result = round(result, self.precision)
                if result == int(result):
                    return int(result)
            
            return result
            
        except Exception as e:
            logger.debug(f"Calculator evaluation failed: {e}")
            return None
    
    def _eval_node(self, node: ast.AST) -> Union[float, int]:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant: {type(node.value)}")
        
        if isinstance(node, ast.Num):
            return node.n
        
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_func = self.OPERATORS.get(type(node.op))
            if op_func:
                return op_func(operand)
            raise ValueError(f"Unsupported unary operator")
        
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_func = self.OPERATORS.get(type(node.op))
            if op_func:
                if isinstance(node.op, (ast.Div, ast.FloorDiv)) and right == 0:
                    raise ValueError("Division by zero")
                return op_func(left, right)
            raise ValueError(f"Unsupported binary operator")
        
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id.lower()
                if func_name in self.FUNCTIONS:
                    args = [self._eval_node(arg) for arg in node.args]
                    return self.FUNCTIONS[func_name](*args)
            raise ValueError(f"Unsupported function")
        
        if isinstance(node, ast.Name):
            raise ValueError(f"Unknown variable: {node.id}")
        
        raise ValueError(f"Unsupported node type")


# =============================================================================
# Phase 3: SQL Result Evaluator
# =============================================================================

@dataclass
class EvaluationResult:
    """Result of SQL evaluation."""
    is_valid: bool
    confidence: float
    issues: List[str]
    suggestions: List[str]
    corrected_value: Optional[Any] = None


class SQLResultEvaluator:
    """Evaluates SQL query results for correctness."""
    
    def __init__(self):
        self.calculator = SafeCalculator()
    
    def evaluate_result(
        self,
        query: str,
        result: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> EvaluationResult:
        """Evaluate SQL query result for correctness."""
        issues = []
        suggestions = []
        confidence = 1.0
        
        if not result.get("success", False):
            return EvaluationResult(
                is_valid=False,
                confidence=0.0,
                issues=[f"SQL failed: {result.get('error', 'Unknown')}"],
                suggestions=["Check SQL syntax", "Verify table/column names"]
            )
        
        rows = result.get("rows", [])
        row_count = result.get("row_count", len(rows))
        
        # Check: Empty results
        if row_count == 0:
            issues.append("No results returned")
            suggestions.append("Check filter conditions")
            confidence *= 0.5
        
        # Check: Truncation
        if result.get("truncated"):
            issues.append("Results truncated")
            confidence *= 0.9
        
        # Check: Single numeric value
        if row_count == 1 and len(rows) == 1:
            row = rows[0]
            if len(row) == 1:
                value = list(row.values())[0]
                self._validate_single_value(value, query, issues, suggestions)
                if issues:
                    confidence *= 0.8
        
        # Check: NULL prevalence
        if rows:
            null_pct = self._check_null_percentage(rows)
            if null_pct > 0.5:
                issues.append(f"High NULL rate: {null_pct:.0%}")
                confidence *= 0.85
        
        is_valid = confidence >= 0.5
        
        return EvaluationResult(
            is_valid=is_valid,
            confidence=round(confidence, 2),
            issues=issues,
            suggestions=suggestions
        )
    
    def _validate_single_value(self, value, query, issues, suggestions):
        query_upper = query.upper()
        
        if value is None:
            issues.append("Result is NULL")
            suggestions.append("Check if column has data")
        
        elif isinstance(value, (int, float)):
            if "COUNT" in query_upper and value < 0:
                issues.append(f"Negative COUNT: {value}")
            
            if value == 0 and any(x in query_upper for x in ['SUM', 'AVG']):
                issues.append("Aggregation returned zero")
    
    def _check_null_percentage(self, rows: List[Dict]) -> float:
        if not rows:
            return 0.0
        
        total_cells = 0
        null_cells = 0
        
        for row in rows:
            for value in row.values():
                total_cells += 1
                if value is None:
                    null_cells += 1
        
        return null_cells / total_cells if total_cells > 0 else 0.0
    
    def try_calculate(self, expression: str) -> Optional[Union[int, float]]:
        """Try to evaluate a simple math expression."""
        return self.calculator.evaluate(expression)
