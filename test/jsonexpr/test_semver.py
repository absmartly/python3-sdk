import unittest

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
