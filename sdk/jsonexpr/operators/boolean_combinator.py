from abc import abstractmethod

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class BooleanCombinator(Operator):

    def evaluate(self, evaluator: Evaluator, args: object):
        if type(args) is list:
            return self.combine(evaluator, args)
        else:
            return None

    @abstractmethod
    def combine(self, evaluator: Evaluator, args: list):
        raise NotImplementedError
