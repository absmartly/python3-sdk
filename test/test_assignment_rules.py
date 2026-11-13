import json
import threading
import unittest

from sdk.audience_matcher import AudienceMatcher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.json.context_data import ContextData
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

    def test_split_percentages_sum_tolerance(self):
        for percentages, accepted in (("33.33/33.33/33.33", True),
                                      ("50/50.01", True),
                                      ("50/50.02", False),
                                      ("49.98/50", False)):
            with self.subTest(percentages=percentages):
                rules = '{"rules":[{"type":"split","percentages":"' + percentages + '"}]}'
                action = self.matcher.evaluate_rules(rules, None, {})
                self.assertEqual(accepted, action is not None)

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
        self.fixture = fixture
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

    def test_rule_assignment_dropped_when_refresh_removes_experiment(self):
        context = self.create_context()
        context.set_attribute("tier", "gold")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))

        empty = ContextData()
        empty.experiments = []
        self.fixture.client._refresh_data = empty
        context.refresh()
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        exposures = [e for e in context.exposures if e.name == "exp_test_ab"]
        self.assertEqual(1, len(exposures))
        self.assertEqual(1, exposures[0].variant)
        self.assertTrue(exposures[0].ruleOverride)
        context.close()

    def test_unexposed_rule_assignment_exposes_control_after_removal(self):
        context = self.create_context()
        context.set_attribute("tier", "gold")
        self.assertEqual(1, context.peek_treatment("exp_test_ab"))

        empty = ContextData()
        empty.experiments = []
        self.fixture.client._refresh_data = empty
        context.refresh()
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        exposures = [e for e in context.exposures if e.name == "exp_test_ab"]
        self.assertEqual(1, len(exposures))
        self.assertEqual(0, exposures[0].variant)
        self.assertFalse(exposures[0].ruleOverride)
        context.close()

    def test_concurrent_split_rule_recheck_does_not_deadlock(self):
        rules = json.dumps({"rules": [{
            "type": "split", "percentages": "0/100",
            "conditions": {"eq": [{"var": "tier"}, {"value": "gold"}]}}]})
        context = self.create_context(rules)
        context.set_attribute("tier", "free")
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))
        context.hashed_units.clear()
        context.assigners.clear()
        context.set_attribute("tier", "gold")

        # Hold both readers inside rule resolution together, so a re-check
        # that computed the unit hash under the read lock would deadlock.
        together = threading.Barrier(2, timeout=0.5)
        evaluate_rules = context.audience_matcher.evaluate_rules

        def evaluate_rules_together(*args):
            try:
                together.wait()
            except threading.BrokenBarrierError:
                pass
            return evaluate_rules(*args)

        context.audience_matcher.evaluate_rules = evaluate_rules_together
        results = []

        def read():
            results.append(context.peek_treatment("exp_test_ab"))

        threads = [threading.Thread(target=read, daemon=True)
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual([1, 1], results)
        context.close()

    def test_rule_assignment_after_experiment_removed_and_reintroduced(self):
        context = self.create_context()
        context.set_attribute("tier", "gold")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        data = context.get_data()

        empty = ContextData()
        empty.experiments = []
        self.fixture.client._refresh_data = empty
        context.refresh()
        self.assertEqual(0, context.get_treatment("exp_test_ab"))

        self.fixture.client._refresh_data = data
        context.refresh()
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        exposures = [e for e in context.exposures if e.name == "exp_test_ab"]
        self.assertEqual([(1, True), (1, True)],
                         [(e.variant, e.ruleOverride) for e in exposures])
        context.close()

    def test_repeated_rule_transitions(self):
        context = self.create_context()
        for _ in range(3):
            context.set_attribute("tier", "gold")
            self.assertEqual(1, context.peek_treatment("exp_test_ab"))
            self.assertEqual(
                "large", context.peek_variable_value("banner.size", "default"))
            context.set_attribute("tier", "free")
            self.assertEqual(0, context.peek_treatment("exp_test_ab"))
            self.assertEqual(
                "default", context.peek_variable_value("banner.size", "default"))
        self.assertEqual([], context.exposures)
        context.close()

    def create_context_without_unit(self, rules):
        context = self.create_context(rules)
        context.units.pop("session_id")
        context.hashed_units.clear()
        context.assigners.clear()
        context.assignment_cache.clear()
        return context

    def test_split_rule_applies_once_unit_is_set(self):
        rules = json.dumps({"rules": [{"type": "split", "percentages": "0/100"}]})
        context = self.create_context_without_unit(rules)
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))
        context.set_unit("session_id", "e791e240fcd3df7d238cfc285f475e8152fcc0ec")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        self.assertTrue(context.exposures[-1].ruleOverride)
        context.close()

    def test_exposed_assignment_stays_pinned_when_unit_is_set(self):
        rules = json.dumps({"rules": [{"type": "split", "percentages": "0/100"}]})
        context = self.create_context_without_unit(rules)
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        context.set_unit("session_id", "e791e240fcd3df7d238cfc285f475e8152fcc0ec")
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertEqual(1, len(context.exposures))
        context.close()
