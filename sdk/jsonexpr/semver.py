from sdk.jsonexpr.expr_evaluator import ExprEvaluator


def _identifiers(value):
    text = value
    if text.startswith(("v", "V")):
        text = text[1:]
    text = text.split("+", 1)[0]
    if not text:
        return None
    core, separator, prerelease = text.partition("-")
    if not core:
        return None
    return core.split("."), prerelease.split(".") if separator else []


def _numeric(value):
    return value.isdigit() and bool(value)


def _compare_identifier(lhs, rhs):
    left_numeric = _numeric(lhs)
    right_numeric = _numeric(rhs)
    if left_numeric and right_numeric:
        left = lhs.lstrip("0") or "0"
        right = rhs.lstrip("0") or "0"
        return (left > right) - (left < right)
    if left_numeric != right_numeric:
        return -1 if left_numeric else 1
    return (lhs > rhs) - (lhs < rhs)


def compare_semver(lhs, rhs):
    """Compare the SDK semantic-version representation, or return None."""
    if not isinstance(lhs, str) or not isinstance(rhs, str) or not lhs or not rhs:
        return None
    left = _identifiers(lhs)
    right = _identifiers(rhs)
    if left is None or right is None:
        return None
    left_core, left_pre = left
    right_core, right_pre = right
    for index in range(max(len(left_core), len(right_core))):
        result = _compare_identifier(
            left_core[index] if index < len(left_core) else "0",
            right_core[index] if index < len(right_core) else "0",
        )
        if result:
            return result
    if not left_pre and not right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    for index in range(max(len(left_pre), len(right_pre))):
        if index >= len(left_pre):
            return -1
        if index >= len(right_pre):
            return 1
        result = _compare_identifier(left_pre[index], right_pre[index])
        if result:
            return result
    return 0


class SemverOperator:
    def evaluate(self, evaluator: ExprEvaluator, args: object):
        if not isinstance(args, list) or len(args) != 2:
            return None
        lhs = evaluator.evaluate(args[0])
        rhs = evaluator.evaluate(args[1])
        result = compare_semver(evaluator.string_convert(lhs), evaluator.string_convert(rhs))
        return None if result is None else self.apply(result)

    def apply(self, result):
        raise NotImplementedError


class SemverEqualsOperator(SemverOperator):
    def apply(self, result):
        return result == 0


class SemverGreaterThanOperator(SemverOperator):
    def apply(self, result):
        return result > 0


class SemverGreaterThanOrEqualOperator(SemverOperator):
    def apply(self, result):
        return result >= 0


class SemverLessThanOperator(SemverOperator):
    def apply(self, result):
        return result < 0


class SemverLessThanOrEqualOperator(SemverOperator):
    def apply(self, result):
        return result <= 0


__all__ = ["compare_semver", "SemverEqualsOperator", "SemverGreaterThanOperator",
           "SemverGreaterThanOrEqualOperator", "SemverLessThanOperator",
           "SemverLessThanOrEqualOperator"]
