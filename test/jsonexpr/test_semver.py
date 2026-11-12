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
