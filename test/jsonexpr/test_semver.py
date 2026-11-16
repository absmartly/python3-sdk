import unittest

from sdk.jsonexpr import semver
from sdk.jsonexpr.json_expr import JsonExpr


class SemverTest(unittest.TestCase):
    def setUp(self):
        self.expr = JsonExpr()

    def test_comparisons(self):
        for operator, expected in (("semver_eq", True), ("semver_gt", False),
                                   ("semver_gte", True), ("semver_lt", False),
                                   ("semver_lte", True)):
            with self.subTest(operator=operator):
                self.assertEqual(expected, self.expr.evaluate_boolean_expr(
                    {operator: [{"value": "v1.2.3"}, {"value": "1.2.3+build"}]}, {}))

    def test_prerelease_order(self):
        self.assertTrue(self.expr.evaluate_boolean_expr(
            {"semver_lt": [{"value": "1.0.0-alpha"}, {"value": "1.0.0"}]}, {}))
        self.assertTrue(self.expr.evaluate_boolean_expr(
            {"semver_gt": [{"value": "1.0.0-2"}, {"value": "1.0.0-1"}]}, {}))

    def test_invalid_version_returns_none(self):
        self.assertIsNone(self.expr.evaluate_expr(
            {"semver_eq": [{"value": "v"}, {"value": "1.0.0"}]}, {}))

    def test_numbers_convert_like_js_string_convert(self):
        # JS Evaluator.stringConvert: toFixed(15) (round half up on the
        # exact binary value, ToString from 1e21) with trailing zeros and
        # the dot removed by /\.?0{0,15}$/. Vectors recorded with Node.
        cases = (
            (1e-7, "0.0000001"),
            (0.1 + 0.2, "0.3"),
            (1.0000000000000002, "1"),
            (123.456, "123.456000000000003"),
            (-1.5, "-1.5"),
            (-2.5e-8, "-0.000000025"),
            (1e-16, "0"),
            (-1e-16, "-0"),
            (5e-16, "0.000000000000001"),
            (1.52587890625e-05, "0.000015258789063"),
            (-1.52587890625e-05, "-0.000015258789063"),
            (0.12345678901234568, "0.123456789012346"),
            (100, "100"),
            (0, "0"),
            (1.25, "1.25"),
            (1e20, "100000000000000000000"),
            (999999999999999900000, "999999999999999868928"),
            (9007199254740993, "9007199254740992"),
            (1e21, "1e+21"),
            (-1e21, "-1e+21"),
            (1.2345e25, "1.2345e+25"),
            (1e30, "1e+3"),
            (1.5e300, "1.5e+3"),
            (10 ** 400, "Infinity"),
            (-10 ** 400, "-Infinity"),
            (float("inf"), "Infinity"),
            (float("-inf"), "-Infinity"),
            (float("nan"), "NaN"),
            (True, "true"),
            (False, "false"),
            ("1.0.0", "1.0.0"),
            (None, None),
            ([1], None),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, semver._to_string(value))

    def test_numeric_versions_compare_like_js(self):
        self.assertEqual(0, semver.compare_versions(1e-7, "0.0000001"))
        self.assertEqual(0, semver.compare_versions(2, "2.0.0"))
        self.assertEqual(-1, semver.compare_versions(1.5, "1.10"))
        self.assertTrue(self.evaluate("semver_eq", 1e-7, "0.0000001"))
        self.assertTrue(self.evaluate("semver_eq", 0.1 + 0.2, "0.3"))

    def test_other_operators_keep_their_number_conversion(self):
        # Only the semver operators use the JS number formatting.
        self.assertFalse(self.expr.evaluate_boolean_expr(
            {"match": [{"value": 1e-7}, {"value": "^0\\.0000001$"}]}, {}))

    def evaluate(self, operator, lhs, rhs):
        return self.expr.evaluate_expr(
            {operator: [{"var": "v"}, {"value": rhs}]}, {"v": lhs})

    def test_cross_sdk_scenarios(self):
        # Scenarios 315-319; expected results were recorded from the
        # JavaScript SDK (@absmartly/javascript-sdk 1.14.0).
        cases = (
            ("semver_eq", "v1.2.3", "1.2.3", True),
            ("semver_eq", "1.2", "1.2.0", True),
            ("semver_eq", "1.0.0+a", "1.0.0+b", True),
            ("semver_eq", "1.2.3", "1.2.4", False),
            ("semver_eq", "1.0.0-rc.1", "1.0.0", False),
            ("semver_gt", "1.10.0", "1.9.9", True),
            ("semver_gt", "2.0.0", "1.10.0", True),
            ("semver_gt", "1.0.0", "1.0.0", False),
            ("semver_gt", "1.0.0+b", "1.0.0+a", False),
            ("semver_gte", "1.0.0", "1.0.0", True),
            ("semver_gte", "0.9.10", "1.0.0", False),
            ("semver_gte", "1.0.0+build.9", "1.0.0", True),
            ("semver_lt", "1.9.9", "1.10.0", True),
            ("semver_lt", "1.0.0-alpha", "1.0.0", True),
            ("semver_lt", "1.0.0", "1.0.0", False),
            ("semver_lte", "1.0.0", "1.0.0", True),
            ("semver_lte", "1.0.1", "1.0.0", False),
            ("semver_lte", "1.0.0-rc.1", "1.0.0", True),
            ("semver_lt", "1.0.0-alpha", "1.0.0-alpha.1", True),
            ("semver_lt", "1.0.0-alpha.1", "1.0.0-alpha.beta", True),
            ("semver_lt", "1.0.0-alpha.beta", "1.0.0-beta", True),
            ("semver_lt", "1.0.0-beta", "1.0.0-beta.2", True),
            ("semver_lt", "1.0.0-beta.2", "1.0.0-beta.11", True),
            ("semver_lt", "1.0.0-beta.11", "1.0.0-rc.1", True),
            ("semver_lt", "1.0.0-rc.1", "1.0.0", True),
            ("semver_gt", "1.0.0-beta.11", "1.0.0-beta.2", True),
            ("semver_eq", "", "1.0.0", None),
            ("semver_eq", "v", "1.0.0", None),
            ("semver_eq", "+build", "1.0.0", None),
            ("semver_gte", None, "1.0.0", None),
            ("semver_lte", "1.0.0", "", None),
            ("semver_gt", 2, "1.9.9", True),
            ("semver_gt", "abc", "1.0.0", True),
            ("semver_lt", "abc", "1.0.0", False),
        )
        for operator, lhs, rhs, expected in cases:
            with self.subTest(operator=operator, lhs=lhs, rhs=rhs):
                self.assertEqual(expected, self.evaluate(operator, lhs, rhs))
