import json
import unittest

from sdk.audience_matcher import AudienceMatcher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from test.test_system_attributes import SystemAttributesTest


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


class ContextAssignmentRulesTest(unittest.TestCase):
    rules = json.dumps({"rules": [{
        "type": "assign", "variant": 1,
        "conditions": {"eq": [{"var": "tier"}, {"value": "gold"}]}}]})

    def create_context(self, rules=None):
        fixture = SystemAttributesTest()
        fixture.set_up()
        data = fixture.strict_audience_data([{"value": True}])
        experiment = data.experiments[0]
        experiment.audienceStrict = False
        experiment.split = [1.0, 0.0]
        experiment.assignmentRules = rules if rules is not None else self.rules
        return fixture.create_context(data)

    def test_rule_applies_after_attribute_starts_matching(self):
        context = self.create_context()
        context.set_attribute("tier", "free")
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))

        context.set_attribute("tier", "gold")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        self.assertTrue(context.exposures[-1].ruleOverride)
        self.assertEqual("large",
                         context.get_variable_value("banner.size", "default"))

        context.set_attribute("tier", "free")
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))
        context.close()

    def test_unrelated_attribute_change_keeps_cached_assignment(self):
        context = self.create_context()
        context.set_attribute("tier", "gold")
        first = context.get_assignment("exp_test_ab")
        context.set_attribute("country", "pt")
        self.assertIs(first, context.get_assignment("exp_test_ab"))
        context.close()

    def test_rule_win_stays_cached_with_different_custom_assignment(self):
        context = self.create_context()
        context.set_attribute("tier", "gold")
        first = context.get_assignment("exp_test_ab")
        context.set_custom_assignment("exp_test_ab", 0)
        self.assertIs(first, context.get_assignment("exp_test_ab"))
        context.close()
