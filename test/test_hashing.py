import unittest

from sdk.internal.hashing import hash_unit


class HashingTest(unittest.TestCase):
    def test_hash_unit(self):
        test_cases = [
            ["", "1B2M2Y8AsgTpgAmY7PhCfg"],
            ["testy", "K5I_V6RgP8c6sYKz-TVn8g"],
            ["bleh@absmartly.com", "IuqYkNRfEx5yClel4j3NbA"],
            ["4a42766ca6313d26f49985e799ff4f3790fb86efa0fce46edb3ea8fbf1ea3408",  # noqa: E501
             "H2jvj6o9YcAgNdhKqEbtWw"],
            ["special characters açb↓c", "4PIrO7lKtTxOcj2eMYlG7A"],
        ]
        for unit, expected in test_cases:
            actual = hash_unit(unit)
            self.assertEqual(expected, actual)
            self.assertIsInstance(actual, str)

    def test_hash_unit_has_no_padding(self):
        self.assertNotIn("=", hash_unit("bleh@absmartly.com"))
