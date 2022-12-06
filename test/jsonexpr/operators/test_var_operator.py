import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.var_operator import VarOperator


class VarOperatorTest(unittest.TestCase):
    operator = VarOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertIsNone(self.operator.evaluate(self.evaluator, [None]))
        self.assertIsNone(self.operator.evaluate(self.evaluator, True))
        self.assertIsNone(self.operator.evaluate(self.evaluator, "ba"))
        self.assertIsNone(self.operator.evaluate(self.evaluator, {}))
        self.assertIsNone(self.operator.evaluate(self.evaluator, []))
