from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator


class GreaterThanOperator(BinaryOperator):
    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        result = evaluator.compare(lhs, rhs)
        return result > 0 if result is not None else None
