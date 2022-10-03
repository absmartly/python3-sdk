import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.in_operator import InOperator


class InTest(unittest.TestCase):
    operator = InOperator()
    evaluator = ExprEvaluator(JsonExpr().operators,        {
            "a": 1,
            "b": True,
            "c": False,
            "d": [1,2,3],
            "e": [1, {"z":2},3],
            "f": {"y": {"x": 3, "0": 10}}
        })

    def test_in(self):
        self.assertFalse(self.operator.binary(self.evaluator, "y", "f"))
        self.assertFalse(self.operator.binary(self.evaluator, 0, 1))