import re
import signal
from contextlib import contextmanager
import logging

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator

logger = logging.getLogger(__name__)


@contextmanager
def timeout(seconds):
    def timeout_handler(signum, frame):
        raise TimeoutError("Regex execution timeout")

    try:
        original_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original_handler)
    except (AttributeError, ValueError):
        yield


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
                    with timeout(self.REGEX_TIMEOUT_SECONDS):
                        return bool(compiled.match(text))
                except re.error as e:
                    logger.warning(f"Invalid regex pattern: {e}")
                    return None
                except TimeoutError:
                    logger.warning(f"Regex execution timeout (potential ReDoS)")
                    return None
                except Exception as e:
                    logger.error(f"Unexpected error in regex matching: {e}")
                    return None
        return None
