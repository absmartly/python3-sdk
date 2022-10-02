from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.unary_operator import UnaryOperator


class NotOperator(UnaryOperator):
    def unary(self, evaluator: Evaluator, arg: object):
        return evaluator.boolean_convert(arg) is not True
    