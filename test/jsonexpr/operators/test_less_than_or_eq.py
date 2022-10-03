import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.less_than_or_equal_operator import LessThanOrEqualOperator


class LessThanOrEqOperatorTest(unittest.TestCase):
    operator = LessThanOrEqualOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_less_than(self):
        self.assertFalse(self.operator.binary(self.evaluator, 1, 0))
        self.assertTrue(self.operator.binary(self.evaluator, 0, 1))