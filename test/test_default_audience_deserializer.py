import unittest

from sdk.default_audience_deserializer import DefaultAudienceDeserializer


class DefaultAudienceDataDeserializerTest(unittest.TestCase):
    def test_deserialize(self):
        deser = DefaultAudienceDeserializer()
        audience = \
            "{\"filter\":[{\"gte\":[{\"var\":\"age\"},{\"value\":20.0}]}]}"
        actual = deser.deserialize(bytes(audience, encoding="utf-8"),
                                   0,
                                   len(audience))
        expected = {"filter": [{
            "gte": [{
                "var": "age"
            }, {
                "value": 20.0
            }]
        }]}
        self.assertEqual(expected, actual)

    def test_deserializer_incorrect(self):
        deser = DefaultAudienceDeserializer()
        audience = \
            "{\"filter\":[{\"gte\":[{\"var\":\"age\"},{\"value\":20.0}]]}"
        actual = deser.deserialize(bytes(audience, encoding="utf-8"),
                                   0,
                                   len(audience))
        self.assertEqual(None, actual)

    def test_deserialize_uses_offset_and_length(self):
        deser = DefaultAudienceDeserializer()
        prefix = b"JUNK"
        payload = b'{"key": "value"}'
        suffix = b"MOREJUNK"
        full = prefix + payload + suffix
        actual = deser.deserialize(full, len(prefix),
                                   len(payload))
        self.assertEqual({"key": "value"}, actual)

    def test_deserialize_null_with_offset(self):
        deser = DefaultAudienceDeserializer()
        data = b"XXXXnullYYYY"
        actual = deser.deserialize(data, 4, 4)
        self.assertIsNone(actual)
