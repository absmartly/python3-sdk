import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.or_combinator import OrCombinator


class NullOperatorTest(unittest.TestCase):
    operator = OrCombinator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertFalse(self.operator.combine(self.evaluator, [None]))
        self.assertFalse(self.operator.combine(self.evaluator, [True]))
        self.assertFalse(self.operator.combine(self.evaluator, [True, False, True]))
