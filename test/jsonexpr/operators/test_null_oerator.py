import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.null_operator import NullOperator


class NullOperatorTest(unittest.TestCase):
    operator = NullOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertTrue(self.operator.unary(self.evaluator, None))
        self.assertFalse(self.operator.unary(self.evaluator, True))
