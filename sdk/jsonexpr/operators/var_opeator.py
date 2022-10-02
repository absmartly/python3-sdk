from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class VarOperator(Operator):
    def evaluate(self, evaluator: Evaluator, path: object):
        if type(path) is dict:
            path = path["path"]

        return evaluator.extract_var(path) if type(path) is str else None
