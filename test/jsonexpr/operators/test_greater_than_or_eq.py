import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.greater_than_or_equal_operator import GreaterThanOrEqualOperator


class GreaterThanOrEqOperatorTest(unittest.TestCase):
    operator = GreaterThanOrEqualOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_gteor(self):
        self.assertTrue(self.operator.binary(self.evaluator, 1, 0))
        self.assertFalse(self.operator.binary(self.evaluator, 0, 1))