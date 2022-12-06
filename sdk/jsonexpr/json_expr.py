from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.operators.and_combinator import AndCombinator
from sdk.jsonexpr.operators.equals_operator import EqualsOperator
from sdk.jsonexpr.operators.greater_than_operator import GreaterThanOperator
from sdk.jsonexpr.operators.greater_than_or_equal_operator \
    import GreaterThanOrEqualOperator
from sdk.jsonexpr.operators.in_operator import InOperator
from sdk.jsonexpr.operators.less_than_operator import LessThanOperator
from sdk.jsonexpr.operators.less_than_or_equal_operator \
    import LessThanOrEqualOperator
from sdk.jsonexpr.operators.match_operator import MatchOperator
from sdk.jsonexpr.operators.not_operator import NotOperator
from sdk.jsonexpr.operators.null_operator import NullOperator
from sdk.jsonexpr.operators.or_combinator import OrCombinator
from sdk.jsonexpr.operators.value_operator import ValueOperator
from sdk.jsonexpr.operators.var_operator import VarOperator


class JsonExpr:
    operators = {
        "and": AndCombinator(),
        "or": OrCombinator(),
        "value": ValueOperator(),
        "var": VarOperator(),
        "null": NullOperator(),
        "not": NotOperator(),
        "in": InOperator(),
        "match": MatchOperator(),
        "eq": EqualsOperator(),
        "gt": GreaterThanOperator(),
        "gte": GreaterThanOrEqualOperator(),
        "lt": LessThanOperator(),
        "lte": LessThanOrEqualOperator()
    }

    def evaluate_boolean_expr(self, expr: object, var: dict):
        evaluator = ExprEvaluator(self.operators, var)
        return evaluator.boolean_convert(evaluator.evaluate(expr))

    def evaluate_expr(self, expr: object, var: dict):
        evaluator = ExprEvaluator(self.operators, var)
        return evaluator.evaluate(expr)
