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
