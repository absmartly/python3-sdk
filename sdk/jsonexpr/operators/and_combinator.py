from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.boolean_combinator import BooleanCombinator


class AndCombinator(BooleanCombinator):

    def combine(self, evaluator: Evaluator, exprs: list):
        for item in exprs:
            if not evaluator.boolean_convert(evaluator.evaluate(item)):
                return False
        return True
