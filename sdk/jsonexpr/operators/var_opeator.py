from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operator import Operator


class VarOperator(Operator):
    def evaluate(self, evaluator: Evaluator, path: object):
        if type(path) is dict:
            if "path" not in path:
                path = None
            else:
                path = path["path"]
        return evaluator.extract_var(path) if type(path) is str else None
