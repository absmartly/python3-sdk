from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator


class EqualsOperator(BinaryOperator):
    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        result = evaluator.compare(lhs, rhs)
        if result is not None:
            return result == 0
        else:
            return None
