from abc import abstractmethod

from sdk.jsonexpr.evaluator import Evaluator


class Operator:

    @abstractmethod
    def evaluate(self, evaluator: Evaluator, args: object):
        raise NotImplementedError
