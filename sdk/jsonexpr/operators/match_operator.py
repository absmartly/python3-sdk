import logging
import multiprocessing
import re

from sdk.jsonexpr.evaluator import Evaluator
from sdk.jsonexpr.operators.binary_operator import BinaryOperator

logger = logging.getLogger(__name__)


def _match_in_process(pattern, text, connection):
    try:
        connection.send(("ok", bool(re.match(pattern, text))))
    except re.error as error:
        connection.send(("invalid", str(error)))
    except Exception as error:
        connection.send(("error", str(error)))
    finally:
        connection.close()


class MatchOperator(BinaryOperator):
    MAX_PATTERN_LENGTH = 1000
    REGEX_TIMEOUT_SECONDS = 1

    def binary(self, evaluator: Evaluator, lhs: object, rhs: object):
        text = evaluator.string_convert(lhs)
        if text is None:
            return None
        pattern = evaluator.string_convert(rhs)
        if pattern is None:
            return None
        if len(pattern) > self.MAX_PATTERN_LENGTH:
            logger.warning("Regex pattern too long (%s chars), rejecting",
                           len(pattern))
            return None

        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_match_in_process,
                                  args=(pattern, text, sender), daemon=True)
        started = False
        try:
            process.start()
            started = True
            sender.close()
            if not receiver.poll(self.REGEX_TIMEOUT_SECONDS):
                logger.warning("Regex execution timeout (potential ReDoS)")
                return None
            status, result = receiver.recv()
            if status == "ok":
                return result
            if status == "invalid":
                logger.warning("Invalid regex pattern: %s", result)
            else:
                logger.error("Unexpected error in regex matching: %s", result)
            return None
        except Exception:
            logger.exception("Unexpected error in regex matching")
            return None
        finally:
            sender.close()
            receiver.close()
            if started:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=self.REGEX_TIMEOUT_SECONDS)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=self.REGEX_TIMEOUT_SECONDS)
            process.close()
