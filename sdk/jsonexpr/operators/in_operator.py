from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator


class InOperator(BinaryOperator):
    def binary(self, evaluator: Evaluator, haystack: object, needle: object):
        if type(haystack) is list:
            for item in haystack:
                if evaluator.compare(item, needle) == 0:
                    return True
            return False
        elif type(haystack) is str or type(haystack) is dict:
            needle_str = evaluator.string_convert(needle)
            return needle_str is not None and needle_str in haystack
        else:
            return None
