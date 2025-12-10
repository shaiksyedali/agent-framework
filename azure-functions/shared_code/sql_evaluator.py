"""
SQL Evaluation and Calculator Utilities

Phase 3: Evaluation LLM - Validates SQL results for correctness
Phase 4: Calculator - Safe expression evaluation for numeric accuracy

These utilities work with both local (SQLite, DuckDB) and Azure SQL databases.
"""

import ast
import json
import logging
import operator
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


# =============================================================================
# Phase 4: Safe Calculator
# =============================================================================

class SafeCalculator:
    """
    Safe mathematical expression evaluator.
    
    Evaluates arithmetic expressions without using eval() for security.
    Supports: +, -, *, /, **, %, parentheses, and common math functions.
    
    Example:
        calc = SafeCalculator()
        result = calc.evaluate("(100 * 0.15) + 50")  # Returns 65.0
        result = calc.evaluate("sum(10, 20, 30)")    # Returns 60.0
    """
    
    # Supported operators
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
    
    # Supported functions
    FUNCTIONS = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'avg': lambda *args: sum(args) / len(args) if args else 0,
        'count': len,
    }
    
    def __init__(self, precision: int = 10):
        """
        Initialize calculator.
        
        Args:
            precision: Decimal places for rounding (default: 10)
        """
        self.precision = precision
    
    def evaluate(self, expression: str, variables: Optional[Dict[str, float]] = None) -> Union[float, int, None]:
        """
        Safely evaluate a mathematical expression.
        
        Args:
            expression: Math expression string (e.g., "2 + 3 * 4")
            variables: Optional dict of variable substitutions
            
        Returns:
            Numeric result or None if evaluation fails
            
        Example:
            evaluate("price * quantity", {"price": 10.5, "quantity": 3})
        """
        if not expression or not isinstance(expression, str):
            return None
            
        try:
            # Clean the expression
            expr = expression.strip()
            
            # Substitute variables
            if variables:
                for name, value in variables.items():
                    expr = re.sub(rf'\b{name}\b', str(value), expr)
            
            # Parse and evaluate
            tree = ast.parse(expr, mode='eval')
            result = self._eval_node(tree.body)
            
            # Round to avoid floating point errors
            if isinstance(result, float):
                result = round(result, self.precision)
                # Convert to int if it's a whole number
                if result == int(result):
                    return int(result)
            
            return result
            
        except Exception as e:
            logger.warning(f"Calculator evaluation failed: {e}")
            return None
    
    def _eval_node(self, node: ast.AST) -> Union[float, int]:
        """Recursively evaluate AST node."""
        
        # Numbers
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        
        # Legacy Num for older Python
        if isinstance(node, ast.Num):
            return node.n
        
        # Unary operators (-x, +x)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_func = self.OPERATORS.get(type(node.op))
            if op_func:
                return op_func(operand)
            raise ValueError(f"Unsupported unary operator: {node.op}")
        
        # Binary operators (x + y, x * y, etc.)
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_func = self.OPERATORS.get(type(node.op))
            if op_func:
                # Handle division by zero
                if isinstance(node.op, (ast.Div, ast.FloorDiv)) and right == 0:
                    raise ValueError("Division by zero")
                return op_func(left, right)
            raise ValueError(f"Unsupported binary operator: {node.op}")
        
        # Function calls (sum, avg, min, max)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id.lower()
                if func_name in self.FUNCTIONS:
                    args = [self._eval_node(arg) for arg in node.args]
                    return self.FUNCTIONS[func_name](*args)
            raise ValueError(f"Unsupported function: {node.func}")
        
        # Names (variables) - should have been substituted
        if isinstance(node, ast.Name):
            raise ValueError(f"Unknown variable: {node.id}")
        
        raise ValueError(f"Unsupported node type: {type(node)}")
    
    def is_simple_expression(self, text: str) -> bool:
        """Check if text looks like a mathematical expression."""
        # Contains operators and mostly numbers/operators
        if not text:
            return False
        
        # Remove whitespace
        text = text.strip()
        
        # Quick checks
        has_operator = any(op in text for op in ['+', '-', '*', '/', '%', '**'])
        has_number = bool(re.search(r'\d', text))
        
        # Not an expression if it looks like a SQL query
        sql_keywords = ['SELECT', 'FROM', 'WHERE', 'INSERT', 'UPDATE', 'DELETE']
        is_sql = any(kw in text.upper() for kw in sql_keywords)
        
        return has_operator and has_number and not is_sql


# =============================================================================
# Phase 3: SQL Result Evaluator
# =============================================================================

@dataclass
class EvaluationResult:
    """Result of SQL evaluation."""
    is_valid: bool
    confidence: float  # 0.0 to 1.0
    issues: List[str]
    suggestions: List[str]
    corrected_value: Optional[Any] = None


class SQLResultEvaluator:
    """
    Evaluates SQL query results for correctness and consistency.
    
    This evaluator performs rule-based checks on SQL results to catch
    common errors like empty results, suspicious aggregations, or
    obvious data quality issues.
    
    For more complex validation, it can optionally use an LLM for
    semantic evaluation.
    """
    
    def __init__(self, calculator: Optional[SafeCalculator] = None):
        """
        Initialize evaluator.
        
        Args:
            calculator: Optional SafeCalculator instance for numeric validation
        """
        self.calculator = calculator or SafeCalculator()
    
    def evaluate_result(
        self,
        query: str,
        result: Dict[str, Any],
        expected_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> EvaluationResult:
        """
        Evaluate SQL query result for correctness.
        
        Args:
            query: The SQL query that was executed
            result: The result dictionary from SQL execution
            expected_type: Expected result type (e.g., 'count', 'list', 'single')
            context: Additional context (e.g., user's original question)
            
        Returns:
            EvaluationResult with validation details
        """
        issues = []
        suggestions = []
        confidence = 1.0
        
        # Check for execution errors
        if not result.get("success", False):
            return EvaluationResult(
                is_valid=False,
                confidence=0.0,
                issues=[f"SQL execution failed: {result.get('error', 'Unknown error')}"],
                suggestions=["Check SQL syntax", "Verify table/column names exist"]
            )
        
        rows = result.get("rows", [])
        row_count = result.get("row_count", len(rows))
        
        # Check 1: Empty results
        if row_count == 0:
            issues.append("Query returned no results")
            suggestions.append("Verify filter conditions are not too restrictive")
            suggestions.append("Check if table has data")
            confidence *= 0.5
        
        # Check 2: Truncation
        if result.get("truncated", False):
            issues.append(f"Results truncated - more than {row_count} rows exist")
            suggestions.append("Add more specific WHERE conditions")
            confidence *= 0.9
        
        # Check 3: Single numeric result validation
        if row_count == 1 and len(rows) == 1:
            row = rows[0]
            if len(row) == 1:
                value = list(row.values())[0]
                eval_result = self._validate_single_value(value, query, context)
                issues.extend(eval_result.issues)
                suggestions.extend(eval_result.suggestions)
                confidence *= eval_result.confidence
        
        # Check 4: Aggregation sanity checks
        agg_check = self._check_aggregation_sanity(query, rows)
        issues.extend(agg_check.issues)
        suggestions.extend(agg_check.suggestions)
        confidence *= agg_check.confidence
        
        # Check 5: NULL value prevalence
        null_check = self._check_null_values(rows)
        issues.extend(null_check.issues)
        if null_check.confidence < 1.0:
            confidence *= null_check.confidence
        
        is_valid = len(issues) == 0 or confidence >= 0.7
        
        return EvaluationResult(
            is_valid=is_valid,
            confidence=round(confidence, 2),
            issues=issues,
            suggestions=suggestions
        )
    
    def _validate_single_value(
        self,
        value: Any,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> EvaluationResult:
        """Validate a single value result (e.g., COUNT, SUM, AVG)."""
        issues = []
        suggestions = []
        confidence = 1.0
        
        # Check for suspicious values
        if value is None:
            issues.append("Result is NULL")
            suggestions.append("Check if aggregation column has data")
            confidence *= 0.5
        
        elif isinstance(value, (int, float)):
            # Negative counts are impossible
            if "COUNT" in query.upper() and value < 0:
                issues.append(f"COUNT returned negative value: {value}")
                confidence *= 0.0
            
            # Very large numbers may indicate overflow
            if abs(value) > 1e15:
                issues.append(f"Unusually large value: {value}")
                suggestions.append("Verify calculation logic")
                confidence *= 0.8
            
            # Zero might be unexpected for SUM/AVG
            if value == 0 and any(agg in query.upper() for agg in ['SUM', 'AVG', 'AVERAGE']):
                issues.append("Aggregation returned zero")
                suggestions.append("Verify data exists and is not all NULL")
                confidence *= 0.8
        
        return EvaluationResult(
            is_valid=len(issues) == 0,
            confidence=confidence,
            issues=issues,
            suggestions=suggestions
        )
    
    def _check_aggregation_sanity(self, query: str, rows: List[Dict]) -> EvaluationResult:
        """Check aggregation results for sanity."""
        issues = []
        suggestions = []
        confidence = 1.0
        
        query_upper = query.upper()
        
        # Check for GROUP BY without aggregation (common mistake)
        has_group_by = "GROUP BY" in query_upper
        has_aggregation = any(agg in query_upper for agg in ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX'])
        
        if has_group_by and not has_aggregation:
            issues.append("GROUP BY without aggregation function")
            suggestions.append("Add COUNT, SUM, AVG, MIN, or MAX to GROUP BY query")
            confidence *= 0.7
        
        return EvaluationResult(
            is_valid=len(issues) == 0,
            confidence=confidence,
            issues=issues,
            suggestions=suggestions
        )
    
    def _check_null_values(self, rows: List[Dict]) -> EvaluationResult:
        """Check for excessive NULL values in results."""
        issues = []
        confidence = 1.0
        
        if not rows:
            return EvaluationResult(True, 1.0, [], [])
        
        # Count NULLs per column
        null_counts = {}
        for row in rows:
            for col, value in row.items():
                if col not in null_counts:
                    null_counts[col] = 0
                if value is None:
                    null_counts[col] += 1
        
        # Flag columns with >50% NULL
        for col, count in null_counts.items():
            null_pct = count / len(rows)
            if null_pct > 0.5:
                issues.append(f"Column '{col}' has {null_pct:.0%} NULL values")
                confidence *= 0.9
        
        return EvaluationResult(
            is_valid=True,  # NULLs don't invalidate result
            confidence=confidence,
            issues=issues,
            suggestions=[]
        )
    
    def verify_numeric_result(
        self,
        sql_result: Union[int, float],
        expression: str,
        tolerance: float = 0.001
    ) -> EvaluationResult:
        """
        Verify SQL numeric result against a calculator evaluation.
        
        Useful for validating aggregations like SUM, AVG when the
        expected formula is known.
        
        Args:
            sql_result: The result from SQL query
            expression: Mathematical expression to evaluate
            tolerance: Acceptable difference ratio (default: 0.1%)
            
        Returns:
            EvaluationResult with comparison details
        """
        calc_result = self.calculator.evaluate(expression)
        
        if calc_result is None:
            return EvaluationResult(
                is_valid=True,  # Can't verify, assume valid
                confidence=0.5,
                issues=["Could not evaluate verification expression"],
                suggestions=[]
            )
        
        # Compare results
        if sql_result == calc_result:
            return EvaluationResult(
                is_valid=True,
                confidence=1.0,
                issues=[],
                suggestions=[]
            )
        
        # Check tolerance
        if sql_result != 0:
            diff_ratio = abs(sql_result - calc_result) / abs(sql_result)
            if diff_ratio <= tolerance:
                return EvaluationResult(
                    is_valid=True,
                    confidence=0.95,
                    issues=[f"Minor difference: SQL={sql_result}, Calc={calc_result}"],
                    suggestions=[]
                )
        
        return EvaluationResult(
            is_valid=False,
            confidence=0.3,
            issues=[f"Result mismatch: SQL={sql_result}, Expected={calc_result}"],
            suggestions=["Verify SQL aggregation logic", "Check for data filtering issues"],
            corrected_value=calc_result
        )


# =============================================================================
# Factory Functions
# =============================================================================

def create_evaluator() -> SQLResultEvaluator:
    """Create a configured SQLResultEvaluator instance."""
    return SQLResultEvaluator(calculator=SafeCalculator())


def create_calculator() -> SafeCalculator:
    """Create a configured SafeCalculator instance."""
    return SafeCalculator(precision=10)
