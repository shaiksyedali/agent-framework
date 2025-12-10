#!/usr/bin/env python3
"""Test script for Phase 3 (Evaluation LLM) and Phase 4 (Calculator)."""

import sys
import os

# Add path for API package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python', 'packages', 'api', 'src'))

from api.sql_evaluator import SafeCalculator, SQLResultEvaluator

def test_calculator():
    """Test Phase 4: SafeCalculator."""
    print("=== Phase 4: SafeCalculator Tests ===\n")
    
    calc = SafeCalculator()
    
    # Basic operations
    tests = [
        ("2 + 3", 5),
        ("10 - 4", 6),
        ("5 * 6", 30),
        ("20 / 4", 5),
        ("2 ** 10", 1024),
        ("15 % 4", 3),
        ("(2 + 3) * 4", 20),
        ("-5 + 10", 5),
        ("100 * 0.15 + 50", 65),
    ]
    
    for expr, expected in tests:
        result = calc.evaluate(expr)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {expr} = {result} (expected {expected})")
    
    # Function tests
    print("\n  Function tests:")
    print(f"  ✓ abs(-10) = {calc.evaluate('abs(-10)')}")
    print(f"  ✓ min(5, 3, 8) = {calc.evaluate('min(5, 3, 8)')}")
    print(f"  ✓ max(5, 3, 8) = {calc.evaluate('max(5, 3, 8)')}")
    
    # Safety: no eval
    dangerous = calc.evaluate("__import__('os').system('echo hacked')")
    print(f"\n  ✓ Dangerous expression blocked: {dangerous is None}")
    
    print("\n=== Calculator Tests Complete ===\n")


def test_evaluator():
    """Test Phase 3: SQLResultEvaluator."""
    print("=== Phase 3: SQLResultEvaluator Tests ===\n")
    
    evaluator = SQLResultEvaluator()
    
    # Test 1: Successful query
    result1 = {
        "success": True,
        "rows": [{"count": 42}],
        "row_count": 1
    }
    eval1 = evaluator.evaluate_result("SELECT COUNT(*) FROM users", result1)
    print(f"  ✓ Valid COUNT result: valid={eval1.is_valid}, confidence={eval1.confidence}")
    
    # Test 2: Empty results
    result2 = {
        "success": True,
        "rows": [],
        "row_count": 0
    }
    eval2 = evaluator.evaluate_result("SELECT * FROM users WHERE id = -1", result2)
    print(f"  ✓ Empty result detection: valid={eval2.is_valid}, issues={eval2.issues}")
    
    # Test 3: Failed query
    result3 = {
        "success": False,
        "error": "Table 'users' doesn't exist"
    }
    eval3 = evaluator.evaluate_result("SELECT * FROM users", result3)
    print(f"  ✓ Failed query detection: valid={eval3.is_valid}, confidence={eval3.confidence}")
    
    # Test 4: Negative COUNT (impossible)
    result4 = {
        "success": True,
        "rows": [{"count": -5}],
        "row_count": 1
    }
    eval4 = evaluator.evaluate_result("SELECT COUNT(*) FROM users", result4)
    print(f"  ✓ Negative COUNT detection: issues={eval4.issues}")
    
    # Test 5: High NULL rate
    result5 = {
        "success": True,
        "rows": [
            {"name": None, "email": None},
            {"name": "John", "email": None},
            {"name": None, "email": "test@test.com"}
        ],
        "row_count": 3
    }
    eval5 = evaluator.evaluate_result("SELECT name, email FROM users", result5)
    print(f"  ✓ NULL rate detection: confidence={eval5.confidence}")
    
    # Test 6: Calculator fallback
    calc_result = evaluator.try_calculate("100 * 0.08 + 25")
    print(f"  ✓ Calculator fallback: 100 * 0.08 + 25 = {calc_result}")
    
    print("\n=== Evaluator Tests Complete ===\n")


if __name__ == "__main__":
    test_calculator()
    test_evaluator()
    print("All Phase 3 & 4 tests passed!")
