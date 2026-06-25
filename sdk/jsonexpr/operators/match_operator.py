import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import logging

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator

logger = logging.getLogger(__name__)


class MatchOperator(BinaryOperator):
    MAX_PATTERN_LENGTH = 1000
    REGEX_TIMEOUT_SECONDS = 1

    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        text = evaluator.string_convert(lhs)
        if text is not None:
            pattern = evaluator.string_convert(rhs)
            if pattern is not None:
                if len(pattern) > self.MAX_PATTERN_LENGTH:
                    logger.warning(f"Regex pattern too long ({len(pattern)} chars), rejecting")
                    return None

                try:
                    compiled = re.compile(pattern)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(compiled.match, text)
                        try:
                            result = future.result(
                                timeout=self.REGEX_TIMEOUT_SECONDS
                            )
                            return bool(result)
                        except TimeoutError:
                            logger.warning("Regex execution timeout (potential ReDoS)")
                            future.cancel()
                            return None
                except re.error as e:
                    logger.warning(f"Invalid regex pattern: {e}")
                    return None
                except Exception as e:
                    logger.exception("Unexpected error in regex matching: %s", e)
                    return None
        return None
