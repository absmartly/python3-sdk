from abc import abstractmethod

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class BinaryOperator(Operator):
    def evaluate(self, evaluator: Evaluator, args: object):
        if type(args) is list:
            lhs = evaluator.evaluate(args[0]) if len(args) > 0 else None
            if lhs is not None:
                rhs = evaluator.evaluate(args[1]) if len(args) > 1 else None
                if rhs is not None:
                    return self.binary(evaluator, lhs, rhs)
        return None

    @abstractmethod
    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        raise NotImplementedError
