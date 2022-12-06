from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class ValueOperator(Operator):
    def evaluate(self, evaluator: Evaluator, value: object):
        return value
