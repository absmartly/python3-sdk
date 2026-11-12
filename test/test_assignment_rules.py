import unittest

from sdk.audience_matcher import AudienceMatcher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer


class AssignmentRulesTest(unittest.TestCase):
    def setUp(self):
        self.matcher = AudienceMatcher(DefaultAudienceDeserializer())

    def test_assign_rule_and_environment(self):
        rules = '{"rules":[{"type":"assign","variant":2,"environments":["prod"]}]}'
        self.assertIsNone(self.matcher.evaluate_rules(rules, "dev", {}))
        self.assertEqual(2, self.matcher.evaluate_rules(rules, "prod", {}).variant)

    def test_conditional_split_rule(self):
        rules = '{"rules":[{"type":"split","percentages":"50/50","conditions":{"eq":[{"var":"tier"},{"value":"gold"}]}}]}'
        self.assertIsNone(self.matcher.evaluate_rules(rules, None, {"tier": "free"}))
        action = self.matcher.evaluate_rules(rules, None, {"tier": "gold"})
        self.assertEqual([0.5, 0.5], action.split)

    def test_invalid_rules_are_skipped(self):
        rules = '{"rules":[{"type":"split","percentages":"10/10"},{"type":"assign","variant":1}]}'
        self.assertEqual(1, self.matcher.evaluate_rules(rules, None, {}).variant)

    def test_split_percentages_require_complete_numeric_parts(self):
        for percentages in ("50garbage/50", "50/50x"):
            rules = '{"rules":[{"type":"split","percentages":"' + percentages + '"}]}'
            self.assertIsNone(self.matcher.evaluate_rules(rules, None, {}))
        action = self.matcher.evaluate_rules(
            '{"rules":[{"type":"split","percentages":" 33.3 / 66.7 "}]}',
            None, {})
        self.assertAlmostEqual(0.333, action.split[0])
        self.assertAlmostEqual(0.667, action.split[1])
