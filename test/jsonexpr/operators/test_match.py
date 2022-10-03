import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.match_operator import MatchOperator


class MatchOperatorTest(unittest.TestCase):
    operator = MatchOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertFalse(self.operator.binary(self.evaluator, ",l5abcdefghijk", "ijk$"))
        self.assertTrue(self.operator.binary(self.evaluator, "abcdefghijk", "abc"))