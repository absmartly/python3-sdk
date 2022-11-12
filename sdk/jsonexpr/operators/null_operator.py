from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.unary_operator import UnaryOperator


class NullOperator(UnaryOperator):
    def unary(self, evaluator: Evaluator, arg: object):
        return arg is None
