import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.less_than_operator import LessThanOperator


class LessThanTest(unittest.TestCase):
    operator = LessThanOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_gteor(self):
        self.assertFalse(self.operator.binary(self.evaluator, 1, 0))
        self.assertTrue(self.operator.binary(self.evaluator, 0, 1))