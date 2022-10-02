from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.boolean_combinator import BooleanCombinator


class OrCombinator(BooleanCombinator):
    def combine(self, evaluator: Evaluator, args: list):
        for item in args:
            if evaluator.boolean_convert(evaluator.evaluate(item)):
                return True
        return len(args) == 0
