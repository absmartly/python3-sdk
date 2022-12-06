import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.value_operator import ValueOperator


class ValueOperatorTest(unittest.TestCase):
    operator = ValueOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertEqual([None], self.operator.evaluate(
                             self.evaluator, [None]))
        self.assertEqual(True, self.operator.evaluate(
                             self.evaluator, True))
        self.assertEqual("ba", self.operator.evaluate(
                             self.evaluator, "ba"))
        self.assertEqual({}, self.operator.evaluate(
                             self.evaluator, {}))
        self.assertEqual([], self.operator.evaluate(
                             self.evaluator, []))
