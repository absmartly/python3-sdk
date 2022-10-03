import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.greater_than_operator import GreaterThanOperator


class GreaterThanOperatorTest(unittest.TestCase):
    operator = GreaterThanOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_gte(self):
        self.assertTrue(self.operator.binary(self.evaluator, 1, 0))