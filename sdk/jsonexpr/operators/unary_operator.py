from abc import abstractmethod

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class UnaryOperator(Operator):
    def evaluate(self, evaluator: Evaluator, args: object):
        arg = evaluator.evaluate(args)
        return self.unary(evaluator, arg)

    @abstractmethod
    def unary(self, evaluator: Evaluator, arg: object):
        raise NotImplementedError
