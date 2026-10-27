import unittest
from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_logger import ContextEventLogger, EventType
from sdk.context_publisher import ContextPublisher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.time.fixed_clock import FixedClock
from sdk import utils


def empty_data():
    data = ContextData()
    data.experiments = []
    return data


def done_future(value=None):
    future = Future()
    future.set_result(value)
    return future


class Provider(ContextDataProvider):
    def __init__(self):
        self.next = None

    def get_context_data(self):
        return self.next


class Publisher(ContextPublisher):
    def __init__(self):
        self.next = None
        self.events = []

    def publish(self, context, event):
        self.events.append(event)
        return self.next if self.next is not None else done_future()


class Recorder(ContextEventLogger):
    """Records, for each event, whether the watched future had already
    settled when the event was logged."""

    def __init__(self):
        self.events = []
        self.watch = None

    def handle_event(self, event_type, data):
        settled = self.watch().done() if self.watch else None
        self.events.append((event_type, settled))


class IntegrityParityTest(unittest.TestCase):

    def make(self, data_future, units=None):
        self.provider = Provider()
        self.publisher = Publisher()
        self.logger = Recorder()
        config = ContextConfig()
        config.units = units if units is not None else {"session_id": "abc"}
        config.publish_delay = -1
        config.refresh_interval = 0
        return Context(FixedClock(1_620_000_000_000), config, data_future,
                       self.provider, self.publisher, self.logger,
                       DefaultVariableParser(),
                       AudienceMatcher(DefaultAudienceDeserializer()))

    def test_track_rejects_non_object_properties(self):
        context = self.make(done_future(empty_data()))
        for bad in ([1, 2], "text", 5, True):
            with self.assertRaises(ValueError) as raised:
                context.track("goal1", bad)
            self.assertEqual(
                "Goal 'goal1' properties must be of type object.",
                str(raised.exception))
        self.assertEqual(0, context.get_pending_count())

    def test_track_accepts_object_or_missing_properties(self):
        context = self.make(done_future(empty_data()))
        context.track("goal1", None)
        context.track("goal2", {"a": 1})
        self.assertEqual(2, context.get_pending_count())

    def test_ready_event_logged_before_ready_settles(self):
        data_future = Future()
        context = self.make(data_future)
        self.logger.watch = lambda: context.ready_future
        data_future.set_result(empty_data())
        self.assertEqual([(EventType.READY, False)], self.logger.events)

    def test_error_event_logged_before_failed_ready_settles(self):
        data_future = Future()
        context = self.make(data_future)
        self.logger.watch = lambda: context.ready_future
        data_future.set_exception(RuntimeError("boom"))
        self.assertEqual([(EventType.ERROR, False)], self.logger.events)
        self.assertTrue(context.is_ready())
        self.assertTrue(context.is_failed())

    def test_refresh_event_logged_before_refresh_settles(self):
        context = self.make(done_future(empty_data()))
        pending = Future()
        self.provider.next = pending
        result = context.refresh_async()
        self.logger.events.clear()
        self.logger.watch = lambda: result
        pending.set_result(empty_data())
        self.assertEqual([(EventType.REFRESH, False)], self.logger.events)

    def test_finalize_event_logged_before_close_settles(self):
        context = self.make(done_future(empty_data()))
        context.track("goal1", None)
        pending = Future()
        self.publisher.next = pending
        result = context.close_async()
        self.logger.events.clear()
        self.logger.watch = lambda: result
        pending.set_result(None)
        self.assertEqual(
            [(EventType.PUBLISH, False), (EventType.FINALIZE, False)],
            self.logger.events)

    def test_numeric_unit_kept_as_number(self):
        context = self.make(done_future(empty_data()), units={"user_id": 125})
        context.set_unit("price", 125.75)
        self.assertEqual(125, context.get_unit("user_id"))
        self.assertIsInstance(context.get_unit("user_id"), int)
        self.assertEqual(125.75, context.get_unit("price"))
        self.assertEqual({"user_id": 125, "price": 125.75},
                         context.get_units())

    def test_numeric_unit_hashed_like_js_to_fixed_0(self):
        context = self.make(done_future(empty_data()))
        self.assertEqual(utils.hash_unit("126"),
                         context.get_unit_hash("price", 125.75).decode())
        self.assertEqual(utils.hash_unit("125"), utils.hash_unit(125))

    def test_set_unit_rejects_non_string_non_number(self):
        context = self.make(done_future(empty_data()))
        for bad in (True, None, {"a": 1}, [1]):
            with self.assertRaises(ValueError) as raised:
                context.set_unit("u", bad)
            self.assertEqual("Unit 'u' must be a string or a number.",
                             str(raised.exception))

    def test_set_unit_same_number_again_is_allowed(self):
        context = self.make(done_future(empty_data()), units={"user_id": 125})
        context.set_unit("user_id", 125)
        with self.assertRaises(ValueError):
            context.set_unit("user_id", "125")

    def test_utils_match_js(self):
        self.assertEqual("CY9rzUYh03PK3k6DJie09g", utils.hash_unit("test"))
        self.assertEqual([0xe2, 0x82, 0xac], list(utils.utf8_bytes("\u20ac")))
        self.assertEqual([0xef, 0xbf, 0xbd], list(utils.utf8_bytes("\ud800")))
        self.assertEqual("AQI", utils.base64_url_no_padding(bytes([1, 2])))
        self.assertTrue(utils.is_object({}))
        self.assertFalse(utils.is_object([]))
        self.assertFalse(utils.is_object(None))
        self.assertTrue(utils.is_numeric(1.5))
        self.assertFalse(utils.is_numeric(True))
        self.assertFalse(utils.is_numeric("1"))
        self.assertTrue(utils.is_promise(Future()))
        self.assertFalse(utils.is_promise({}))
        self.assertEqual("126", utils.unit_to_string(125.75))
        self.assertEqual("-126", utils.unit_to_string(-125.5))

    def test_unit_to_string_matches_js_to_fixed_0_boundaries(self):
        cases = {
            -0.0: "0", -0.4: "-0", 0.5: "1", 2.5: "3", 1.005: "1",
            1e20: "100000000000000000000", 1e21: "1e+21",
            1.5e22: "1.5e+22", -1e21: "-1e+21", 1e29: "1e+29",
            12345.0: "12345", 10 ** 21: "1e+21",
        }
        for value, expected in cases.items():
            self.assertEqual(expected, utils.unit_to_string(value), value)

    def test_unit_hash_ignores_caller_decimal_context(self):
        import decimal
        with decimal.localcontext() as ctx:
            ctx.prec = 3
            ctx.traps[decimal.Inexact] = True
            self.assertEqual("12345", utils.unit_to_string(12345.0))
            self.assertEqual("1e+29", utils.unit_to_string(1e29))


if __name__ == '__main__':
    unittest.main()
