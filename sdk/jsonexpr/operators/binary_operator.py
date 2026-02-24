from abc import abstractmethod

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class BinaryOperator(Operator):
    def evaluate(self, evaluator: Evaluator, args: object):
        if type(args) is list and len(args) >= 2:
            lhs = evaluator.evaluate(args[0])
            rhs = evaluator.evaluate(args[1])
            return self.binary(evaluator, lhs, rhs)
        return None

    @abstractmethod
    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        raise NotImplementedError
