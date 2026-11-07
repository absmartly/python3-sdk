import unittest

from sdk.audience_matcher import AudienceMatcher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer


class AudienceMatcherTest(unittest.TestCase):

    def setUp(self):
        self.matcher = AudienceMatcher(DefaultAudienceDeserializer())

    def test_returns_none_on_empty_audience(self):
        result = self.matcher.evaluate("{}", {})
        self.assertIsNone(result)

    def test_returns_none_if_filter_not_object_or_array(self):
        result = self.matcher.evaluate('{"filter": "string_value"}', {})
        self.assertIsNone(result)

        result = self.matcher.evaluate('{"filter": 123}', {})
        self.assertIsNone(result)

        result = self.matcher.evaluate('{"filter": true}', {})
        self.assertIsNone(result)

        result = self.matcher.evaluate('{"filter": null}', {})
        self.assertIsNone(result)

    def test_returns_boolean_for_valid_filter(self):
        audience = '{"filter":[{"gte":[{"var":"age"},{"value":20}]}]}'
        result = self.matcher.evaluate(audience, {"age": 25})
        self.assertIsNotNone(result)
        self.assertTrue(result.result)

        result = self.matcher.evaluate(audience, {"age": 15})
        self.assertIsNotNone(result)
        self.assertFalse(result.result)
