from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator
from sdk.jsonexpr.semver import compare_versions


class SemverOperator(Operator):
    comparison = 0

    def evaluate(self, evaluator: Evaluator, args: object):
        if not isinstance(args, list) or len(args) < 2:
            return None
        lhs = evaluator.evaluate(args[0])
        rhs = evaluator.evaluate(args[1])
        result = compare_versions(lhs, rhs)
        if result is None:
            return None
        return self.matches(result)

    def matches(self, result):
        raise NotImplementedError


class SemverEqualsOperator(SemverOperator):
    def matches(self, result):
        return result == 0


class SemverGreaterThanOperator(SemverOperator):
    def matches(self, result):
        return result > 0


class SemverGreaterThanOrEqualOperator(SemverOperator):
    def matches(self, result):
        return result >= 0


class SemverLessThanOperator(SemverOperator):
    def matches(self, result):
        return result < 0


class SemverLessThanOrEqualOperator(SemverOperator):
    def matches(self, result):
        return result <= 0
