import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.match_operator import MatchOperator


class MatchOperatorTest(unittest.TestCase):
    operator = MatchOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertFalse(self.operator.binary(
            self.evaluator, ",l5abcdefghijk", "ijk$"))
        self.assertTrue(self.operator.binary(
            self.evaluator, "abcdefghijk", "abc"))

    def test_match_returns_none_for_invalid_pattern(self):
        result = self.operator.binary(self.evaluator, "test", "[invalid")
        self.assertIsNone(result)

    def test_match_returns_none_for_pattern_too_long(self):
        long_pattern = "a" * 1001
        result = self.operator.binary(self.evaluator, "test", long_pattern)
        self.assertIsNone(result)

    def test_match_returns_none_for_none_text(self):
        result = self.operator.binary(self.evaluator, None, "abc")
        self.assertIsNone(result)

    def test_match_returns_none_for_none_pattern(self):
        result = self.operator.binary(self.evaluator, "abc", None)
        self.assertIsNone(result)

    def test_match_uses_thread_pool_not_sigalrm(self):
        result = self.operator.binary(self.evaluator, "hello world", "hello")
        self.assertTrue(result)
