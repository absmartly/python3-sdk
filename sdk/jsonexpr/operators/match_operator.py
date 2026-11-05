import re
import logging

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator

logger = logging.getLogger(__name__)


class MatchOperator(BinaryOperator):
    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        text = evaluator.string_convert(lhs)
        if text is not None:
            pattern = evaluator.string_convert(rhs)
            if pattern is not None:
                try:
                    compiled = re.compile(pattern)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern: {e}")
                    return None
                return bool(compiled.match(text))
        return None
