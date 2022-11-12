import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.and_combinator import AndCombinator


class AndCombinatorTest(unittest.TestCase):
    combinator = AndCombinator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_combine_true(self):
        self.assertEqual(False, self.combinator.combine(
            self.evaluator, [True]))

    def test_combine_false(self):
        self.assertEqual(False, self.combinator.combine(
            self.evaluator, [False]))

    def test_combine_null(self):
        self.assertEqual(False, self.combinator.combine(
            self.evaluator, [None]))

    def test_combine_circuit(self):
        self.assertEqual(False, self.combinator.combine(
            self.evaluator, [True, False, True]))

    def test_combine(self):
        self.assertEqual(False, self.combinator.combine(
            self.evaluator, [True, True]))
        self.assertEqual(False, self.combinator.combine(
            self.evaluator, [True, False]))
