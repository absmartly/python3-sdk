import decimal
from decimal import Decimal

from sdk.jsonexpr.evaluator import Evaluator


def compare_to(this, that):
    if this > that:
        return 1
    elif this < that:
        return -1
    elif this == that:
        return 0


class ExprEvaluator(Evaluator):

    def __init__(self, operators: dict, vars: dict):
        self.vars = vars
        self.operators = operators

    def evaluate(self, expr: object):
        if type(expr) is list:
            return self.operators["and"].evaluate(self, expr)
        elif type(expr) is dict:
            for key, value in expr.items():
                if key not in self.operators:
                    return None
                op = self.operators[key]
                if op is not None:
                    res = op.evaluate(self, value)
                    return res
                break
        return None

    def boolean_convert(self, x: object):
        if type(x) is bool:
            return x
        elif type(x) is str:
            return x != "False" and x != "0" and x != ""
        elif type(x) is int or type(x) is float or type(x) is complex:
            return x != 0
        return x is not None

    def number_convert(self, x: object):
        if type(x) is int or type(x) is float or type(x) is complex:
            return x
        elif type(x) is bool:
            return 1.0 if x is True else 0.0
        elif type(x) is str:
            try:
                return Decimal(x)
            except decimal.InvalidOperation:
                return None
        return None

    def string_convert(self, x: object):
        if type(x) is str:
            return x
        elif type(x) is bool:
            return str(x)
        elif type(x) is int or type(x) is float or type(x) is complex:
            return str(x)
        return None

    def extract_var(self, path: str):
        frags = path.split("/")

        target = self.vars if self.vars is not None else {}
        for frag in frags:
            value = None
            if type(target) is list:
                try:
                    value = target[int(frag)]
                except BaseException as err:
                    print(err)
            elif type(target) is dict:
                if frag not in target:
                    return None
                value = target[frag]
            if value is not None:
                target = value
                continue
            return None

        return target

    def compare(self, lhs: object, rhs: object):
        if lhs is None:
            return 0 if rhs is None else None
        elif rhs is None:
            return None
        if type(lhs) is int or type(lhs) is float or type(lhs) is complex:
            rvalue = self.number_convert(rhs)
            if rvalue is not None:
                return compare_to(lhs, rvalue)
        elif type(lhs) is str:
            rvalue = self.string_convert(rhs)
            if rvalue is not None:
                return compare_to(lhs, rvalue)
        elif type(lhs) is bool:
            rvalue = self.boolean_convert(rhs)
            if rvalue is not None:
                return compare_to(lhs, rvalue)
        elif type(lhs) == type(rhs) and lhs == rhs:
            return 0
        return None
