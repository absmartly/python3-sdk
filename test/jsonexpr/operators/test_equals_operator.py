import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.equals_operator import EqualsOperator


class EqualsOperatorTest(unittest.TestCase):
    operator = EqualsOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_equals(self):
        self.assertTrue(self.operator.binary(self.evaluator, 0, 0))