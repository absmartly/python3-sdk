from abc import abstractmethod


class Evaluator:

    @abstractmethod
    def evaluate(self, expr: object):
        raise NotImplementedError

    @abstractmethod
    def boolean_convert(self, x: object):
        raise NotImplementedError

    @abstractmethod
    def number_convert(self, x: object):
        raise NotImplementedError

    @abstractmethod
    def string_convert(self, x: object):
        raise NotImplementedError

    @abstractmethod
    def extract_var(self, path: str):
        raise NotImplementedError

    # returns
    # -1 -> lesser, 0 -> equals, 1 -> greater, null -> undefined comparison
    @abstractmethod
    def compare(self, lhs: object, rhs: object):
        raise NotImplementedError
