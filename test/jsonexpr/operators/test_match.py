import unittest
from unittest.mock import Mock, patch

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr
from sdk.jsonexpr.operators.match_operator import MatchOperator

GET_CONTEXT = ("sdk.jsonexpr.operators.match_operator."
               "multiprocessing.get_context")
TIMEOUT = MatchOperator.REGEX_TIMEOUT_SECONDS


class MatchOperatorTest(unittest.TestCase):
    operator = MatchOperator()
    evaluator = ExprEvaluator(JsonExpr().operators, {})

    def test_match(self):
        self.assertFalse(self.operator.binary(
            self.evaluator, ",l5abcdefghijk", "ijk$"))
        self.assertTrue(self.operator.binary(
            self.evaluator, "abcdefghijk", "abc"))

    def test_match_returns_none_for_invalid_pattern(self):
        result = self.operator.binary(self.evaluator, "test", "[invalid")
        self.assertIsNone(result)

    def test_match_returns_none_for_pattern_too_long(self):
        long_pattern = "a" * 1001
        result = self.operator.binary(self.evaluator, "test", long_pattern)
        self.assertIsNone(result)

    def test_match_returns_none_for_none_text(self):
        result = self.operator.binary(self.evaluator, None, "abc")
        self.assertIsNone(result)

    def test_match_returns_none_for_none_pattern(self):
        result = self.operator.binary(self.evaluator, "abc", None)
        self.assertIsNone(result)

    def test_simple_match_returns_true(self):
        result = self.operator.binary(self.evaluator, "hello world", "hello")
        self.assertTrue(result)

    def test_timeout_terminates_worker_process(self):
        process = Mock()
        process.is_alive.side_effect = [True, False]
        receiver, sender = Mock(), Mock()
        receiver.poll.return_value = False
        context = Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = process

        with patch(GET_CONTEXT, return_value=context):
            self.assertIsNone(
                self.operator.binary(self.evaluator, "aaaa", "(a+)+$"))

        receiver.poll.assert_called_once_with(TIMEOUT)
        process.terminate.assert_called_once()
        process.join.assert_called_once_with(timeout=TIMEOUT)
        process.kill.assert_not_called()
        process.close.assert_called_once()

    def test_unresponsive_worker_process_is_killed(self):
        process = Mock()
        process.is_alive.side_effect = [True, True]
        receiver, sender = Mock(), Mock()
        receiver.poll.return_value = False
        context = Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = process

        with patch(GET_CONTEXT, return_value=context):
            self.assertIsNone(
                self.operator.binary(self.evaluator, "aaaa", "(a+)+$"))

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(2, process.join.call_count)
        process.close.assert_called_once()
