import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.not_operator import NotOperator


class NotOperatorTest(unittest.TestCase):
    operator = NotOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertTrue(self.operator.unary(self.evaluator, False))
        self.assertFalse(self.operator.unary(self.evaluator, True))
