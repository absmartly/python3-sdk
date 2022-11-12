import re

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator


class MatchOperator(BinaryOperator):
    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        text = evaluator.string_convert(lhs)
        if text is not None:
            pattern = evaluator.string_convert(rhs)
            if pattern is not None:
                compiled = re.compile(pattern)
                return bool(compiled.match(text))
        return None
