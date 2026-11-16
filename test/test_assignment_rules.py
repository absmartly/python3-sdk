import json
import threading
import unittest
from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.context import Context
from sdk.context_config import ContextConfig
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

    def test_split_percentages_parse_like_js_parse_float(self):
        # Each part is read like JS parseFloat: leading whitespace is
        # skipped and the longest numeric prefix is used, so trailing text is
        # ignored. Expected splits recorded with Node from javascript-sdk's
        # parseSplitPercentages.
        cases = (
            ("20abc/80", [0.2, 0.8]),
            ("50/50x", [0.5, 0.5]),
            ("50garbage/50", [0.5, 0.5]),
            (" 33.3 / 66.7 ", [0.33299999999999996, 0.667]),
            ("1e/99", [0.01, 0.99]),
            ("0x10/100", [0, 1]),
            ("+50/50", [0.5, 0.5]),
            (".5/99.5", [0.005, 0.995]),
            ("50.0.1/50", [0.5, 0.5]),
            ("\ufeff50/\u00a050", [0.5, 0.5]),
            ("5e1/5e1", [0.5, 0.5]),
            ("abc/def", None),
            ("Infinity/0", None),
            ("-Infinity/100", None),
            ("/100", None),
            ("50/50/", None),
            ("1_0/90", None),
            ("-10/110", None),
            ("\u0665\u0660/50", None),
        )
        for percentages, expected in cases:
            with self.subTest(percentages=percentages):
                rules = json.dumps({"rules": [{"type": "split",
                                               "percentages": percentages}]})
                action = self.matcher.evaluate_rules(rules, None, {})
                self.assertEqual(expected,
                                 action.split if action is not None else None)


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
        # As in the JS SDK, the rebuilt unknown-experiment assignment is a
        # new assignment, so it is exposed again.
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        exposures = [e for e in context.exposures if e.name == "exp_test_ab"]
        self.assertEqual([(1, True), (0, False)],
                         [(e.variant, e.ruleOverride) for e in exposures])
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
        self.assertEqual([(1, True), (0, False), (1, True)],
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

    def test_repeated_set_unit_after_refresh_reintroduction(self):
        uid = "e791e240fcd3df7d238cfc285f475e8152fcc0ec"
        rules = json.dumps({"rules": [{"type": "split", "percentages": "0/100"}]})
        context = self.create_context_without_unit(rules)
        data = context.get_data()
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))

        empty = ContextData()
        empty.experiments = []
        self.fixture.client._refresh_data = empty
        context.refresh()
        self.fixture.client._refresh_data = data
        context.refresh()

        context.set_unit("session_id", uid)
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        context.set_unit("session_id", uid)
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        exposures = [e for e in context.exposures if e.name == "exp_test_ab"]
        self.assertEqual([(1, True)],
                         [(e.variant, e.ruleOverride) for e in exposures])
        context.close()


class CrossSdkRuleScenariosTest(unittest.TestCase):
    """Cross-SDK conformance scenarios; expected results were recorded from
    the JavaScript SDK (@absmartly/javascript-sdk 1.14.0)."""

    def create_context(self, *experiments, units=None):
        fixture = SystemAttributesTest()
        fixture.set_up()
        self.fixture = fixture
        content = json.dumps({"experiments": list(experiments)})
        data = fixture.deser.deserialize(
            bytes(content, encoding="utf-8"), 0, len(content))
        config = ContextConfig()
        config.units = units if units is not None else \
            {"session_id": "svk-unit-1"}
        config.publish_delay = -1
        config.refresh_interval = 0
        data_future = Future()
        data_future.set_result(data)
        return Context(
            fixture.clock, config, data_future,
            fixture.data_provider, fixture.event_handler, None,
            fixture.variable_parser, fixture.audience_matcher,
            fixture.application, fixture.environment)

    def experiment(self, id, name, rules, **extra):
        experiment = {
            "id": id,
            "name": name,
            "iteration": 1,
            "unitType": "session_id",
            "seedHi": 3603515,
            "seedLo": 233373850,
            "split": [0.5, 0.5],
            "trafficSeedHi": 449867249,
            "trafficSeedLo": 455443629,
            "trafficSplit": [0.0, 1.0],
            "fullOnVariant": 0,
            "applications": [{"name": "website"}],
            "variants": [{"name": "A", "config": None},
                         {"name": "B", "config": None}],
            "audienceStrict": False,
            "audience": "",
            "assignmentRules": json.dumps({"rules": rules}),
        }
        experiment.update(extra)
        return experiment

    def exposure_fields(self, exposure):
        return {
            "id": exposure.id, "name": exposure.name, "unit": exposure.unit,
            "variant": exposure.variant, "assigned": exposure.assigned,
            "eligible": exposure.eligible, "overridden": exposure.overridden,
            "fullOn": exposure.fullOn, "custom": exposure.custom,
            "audienceMismatch": exposure.audienceMismatch,
            "ruleOverride": exposure.ruleOverride,
        }

    def test_rule_takes_precedence_over_strict_audience_mismatch(self):
        # Scenario 236: a rule win happens before audience evaluation, so
        # the audience is not evaluated and audienceMismatch stays false.
        context = self.create_context(self.experiment(
            7, "exp_rule_audience",
            [{"name": "a", "type": "assign", "variant": 1}],
            audienceStrict=True,
            audience=json.dumps({"filter": [
                {"eq": [{"var": "tier"}, {"value": "gold"}]}]})))
        self.assertEqual(1, context.get_treatment("exp_rule_audience"))
        self.assertEqual(1, len(context.exposures))
        self.assertEqual({
            "id": 7, "name": "exp_rule_audience", "unit": "session_id",
            "variant": 1, "assigned": False, "eligible": True,
            "overridden": False, "fullOn": False, "custom": False,
            "audienceMismatch": False, "ruleOverride": True,
        }, self.exposure_fields(context.exposures[0]))
        context.close()

    def test_rule_variant_of_removed_experiment_is_rebuilt(self):
        # Scenario 239 (javascript-sdk#67): once a refresh removes the
        # experiment, the cached rule-won assignment is dropped and rebuilt
        # as unknown, which is a new assignment and is exposed again.
        context = self.create_context(self.experiment(
            10, "exp_rule_removed",
            [{"name": "us", "type": "assign", "variant": 1,
              "conditions": {"eq": [{"var": "country"},
                                    {"value": "US"}]}}]))
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_rule_removed"))
        self.assertTrue(context.exposures[0].ruleOverride)
        self.assertEqual(1, context.get_pending_count())

        empty = ContextData()
        empty.experiments = []
        self.fixture.client._refresh_data = empty
        context.refresh()
        self.assertEqual(0, context.peek_treatment("exp_rule_removed"))
        self.assertEqual(0, context.get_treatment("exp_rule_removed"))
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual({
            "id": 0, "name": "exp_rule_removed", "unit": None,
            "variant": 0, "assigned": False, "eligible": True,
            "overridden": False, "fullOn": False, "custom": False,
            "audienceMismatch": False, "ruleOverride": False,
        }, self.exposure_fields(context.exposures[1]))
        context.close()

    def test_split_rule_without_unit_gives_no_unit_result(self):
        # Scenario 309: a split rule that matches while the experiment's
        # unit is missing selects the no-unit result (fullOnVariant) as a
        # rule override, like JS _resolveRule, and the exposed variant stays
        # pinned once the unit is set.
        context = self.create_context(
            self.experiment(441, "exp_rules_late_pinned",
                            [{"name": "late", "type": "split",
                              "percentages": "50/50"}],
                            seedHi=24301, seedLo=5003, split=[1, 0],
                            trafficSeedHi=2827, trafficSeedLo=9011,
                            trafficSplit=[0, 1], audience=None),
            units={"user_id": "parity-user"})
        self.assertEqual(0, context.get_treatment("exp_rules_late_pinned"))
        self.assertEqual({
            "id": 441, "name": "exp_rules_late_pinned", "unit": "session_id",
            "variant": 0, "assigned": False, "eligible": True,
            "overridden": False, "fullOn": False, "custom": False,
            "audienceMismatch": False, "ruleOverride": True,
        }, self.exposure_fields(context.exposures[0]))
        context.set_unit("session_id", "late-unit-1")
        self.assertEqual(0, context.get_treatment("exp_rules_late_pinned"))
        context.set_attribute("tier", "gold")
        self.assertEqual(0, context.get_treatment("exp_rules_late_pinned"))
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_split_rule_without_unit_gives_full_on_variant(self):
        context = self.create_context(
            self.experiment(442, "exp_rules_full_on",
                            [{"type": "split", "percentages": "50/50"}],
                            fullOnVariant=1),
            units={"user_id": "parity-user"})
        self.assertEqual(1, context.get_treatment("exp_rules_full_on"))
        self.assertTrue(context.exposures[0].ruleOverride)
        context.close()

    def test_wrong_count_split_and_negative_assign_stop_rules(self):
        # Scenario 312: a split of the wrong length and an assign rule with
        # a negative variant both match but are out of bounds, so rule
        # evaluation stops there and the unit gets its normal assignment.
        def experiment(id, name, rules):
            return self.experiment(id, name, rules, seedHi=0, seedLo=0,
                                   split=[0.0, 1.0], trafficSeedHi=0,
                                   trafficSeedLo=0, trafficSplit=[0, 1],
                                   audience=None)
        fallback = {"name": "fallback", "type": "assign", "variant": 0}
        context = self.create_context(
            experiment(460, "exp_rules_wrong_count",
                       [{"name": "three", "type": "split",
                         "percentages": "50/25/25"}, fallback]),
            experiment(461, "exp_rules_negative",
                       [{"name": "neg", "type": "assign", "variant": -1},
                        fallback]))
        for id, name in ((460, "exp_rules_wrong_count"),
                         (461, "exp_rules_negative")):
            self.assertEqual(1, context.get_treatment(name))
            self.assertEqual({
                "id": id, "name": name, "unit": "session_id",
                "variant": 1, "assigned": True, "eligible": True,
                "overridden": False, "fullOn": False, "custom": False,
                "audienceMismatch": False, "ruleOverride": False,
            }, self.exposure_fields(context.exposures[-1]))
        self.assertEqual(2, context.get_pending_count())
        context.close()


class RuleRefreshRevalidationTest(CrossSdkRuleScenariosTest):
    """A refresh that changes the assignment-rules text but not the outcome
    keeps the cached (and already exposed) assignment, like the JS SDK's
    audienceMatches; an actual change of result still rebuilds it."""

    def refresh_with(self, context, *experiments):
        content = json.dumps({"experiments": list(experiments)})
        self.fixture.client._refresh_data = self.fixture.deser.deserialize(
            bytes(content, encoding="utf-8"), 0, len(content))
        context.refresh()

    def count_rule_evaluations(self, context):
        calls = []
        evaluate = context.audience_matcher.evaluate_parsed_rules
        parse = context.audience_matcher.parse_rules

        def counting(*args):
            calls.append(args)
            return evaluate(*args)

        def parsing(*args):
            self.parses.append(args)
            return parse(*args)

        self.parses = []
        context.audience_matcher.evaluate_parsed_rules = counting
        context.audience_matcher.parse_rules = parsing
        return calls

    us_rule = {"name": "us", "type": "assign", "variant": 1,
               "conditions": {"eq": [{"var": "country"}, {"value": "US"}]}}

    def test_same_outcome_refresh_keeps_exposed_assignment(self):
        context = self.create_context(
            self.experiment(20, "exp_rule_refresh", [self.us_rule]))
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_rule_refresh"))
        first = context.get_assignment("exp_rule_refresh")

        renamed = dict(self.us_rule, name="renamed", futureField={"x": 1})
        experiment = self.experiment(20, "exp_rule_refresh", [renamed])
        experiment["assignmentRules"] = json.dumps(
            {"rules": [renamed], "futureTop": True}, indent=2)
        self.refresh_with(context, experiment)

        calls = self.count_rule_evaluations(context)
        self.assertEqual(1, context.get_treatment("exp_rule_refresh"))
        self.assertIs(first, context.get_assignment("exp_rule_refresh"))
        self.assertEqual(1, len(calls))
        for _ in range(100):
            self.assertEqual(1, context.get_treatment("exp_rule_refresh"))
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(self.parses))
        for i in range(20):
            context.set_attribute("unrelated", i)
            self.assertEqual(1, context.get_treatment("exp_rule_refresh"))
        self.assertEqual(21, len(calls))
        self.assertEqual(1, len(self.parses))
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_changed_outcome_refresh_rebuilds(self):
        context = self.create_context(
            self.experiment(21, "exp_rule_changed", [self.us_rule],
                            split=[0.0, 1.0]))
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_rule_changed"))

        self.refresh_with(context, self.experiment(
            21, "exp_rule_changed", [dict(self.us_rule, variant=0)],
            split=[0.0, 1.0]))
        self.assertEqual(0, context.get_treatment("exp_rule_changed"))
        self.assertEqual([(1, True), (0, True)],
                         [(e.variant, e.ruleOverride)
                          for e in context.exposures])
        context.close()

    def test_removed_winning_rule_rebuilds(self):
        context = self.create_context(
            self.experiment(22, "exp_rule_gone", [self.us_rule],
                            split=[1.0, 0.0]))
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_rule_gone"))

        for rules in ("", None):
            with self.subTest(rules=rules):
                experiment = self.experiment(22, "exp_rule_gone", [],
                                             split=[1.0, 0.0])
                experiment["assignmentRules"] = rules
                self.refresh_with(context, experiment)
                self.assertEqual(0, context.get_treatment("exp_rule_gone"))
                self.assertFalse(context.exposures[-1].ruleOverride)
        self.assertEqual([(1, True), (0, False)],
                         [(e.variant, e.ruleOverride)
                          for e in context.exposures])
        context.close()

    def test_added_rule_rebuilds_only_when_it_matches(self):
        context = self.create_context(
            self.experiment(23, "exp_rule_added", [], split=[1.0, 0.0]))
        context.set_attribute("country", "PT")
        self.assertEqual(0, context.get_treatment("exp_rule_added"))
        first = context.get_assignment("exp_rule_added")

        self.refresh_with(context, self.experiment(
            23, "exp_rule_added", [self.us_rule], split=[1.0, 0.0]))
        self.assertEqual(0, context.get_treatment("exp_rule_added"))
        self.assertIs(first, context.get_assignment("exp_rule_added"))

        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_rule_added"))
        self.assertEqual([(0, False), (1, True)],
                         [(e.variant, e.ruleOverride)
                          for e in context.exposures])
        context.close()


class MalformedRuleVariantTest(CrossSdkRuleScenariosTest):
    """A malformed assign variant never escapes treatment: like JS
    Number.isInteger, a non-integer (fraction, bool, non-finite, or an
    integer too large for a double, which JSON.parse makes Infinity) skips
    the rule, while a finite out-of-range integer still matches and stops
    rule evaluation (the unit gets its normal assignment)."""

    def test_malformed_variants(self):
        later = {"name": "later", "type": "assign", "variant": 1}
        cases = (
            ("huge_int", "9" * 401, 1, True),
            ("overflow_float", "1e400", 1, True),
            ("negative_overflow_float", "-1e400", 1, True),
            ("negative_huge_int", "-" + "9" * 401, 1, True),
            ("fraction", "1.5", 1, True),
            ("bool", "true", 1, True),
            ("string", '"1"', 1, True),
            ("finite_big_int", "1" + "0" * 300, 0, False),
            ("max_double_int", str(int(1.7976931348623157e308)), 0, False),
            ("integral_float", "0.0", 0, True),
            ("integral_exponent", "0e0", 0, True),
        )
        for label, variant, expected, rule_override in cases:
            with self.subTest(variant=label):
                rules = ('{"rules":[{"name":"bad","type":"assign","variant":'
                         + variant + '},' + json.dumps(later) + ']}')
                bad = self.experiment(30, "exp_bad_variant", [],
                                      split=[1.0, 0.0])
                bad["assignmentRules"] = rules
                healthy = self.experiment(31, "exp_healthy", [],
                                          split=[0.0, 1.0])
                context = self.create_context(bad, healthy)
                self.assertEqual(expected,
                                 context.get_treatment("exp_bad_variant"))
                self.assertEqual(rule_override,
                                 context.exposures[-1].ruleOverride)
                self.assertEqual(1, context.get_treatment("exp_healthy"))
                context.close()


class RuleMutationCoverageTest(CrossSdkRuleScenariosTest):
    """Distinguishing cases for mutants that survived the review's mutation
    run (split seeds, unknown rule types, rule environment scope)."""

    # Per-UID [split seeds, traffic seeds] variants of a 50/50 split,
    # computed with javascript-sdk's VariantAssigner and hashUnit.
    js_split_vectors = {
        "split-uid-0": (1, 0), "split-uid-1": (0, 1), "split-uid-2": (1, 1),
        "split-uid-3": (1, 0), "split-uid-6": (0, 1), "split-uid-8": (0, 0),
        "split-uid-9": (1, 0), "split-uid-10": (0, 1),
    }

    def test_split_rule_uses_experiment_seeds(self):
        for uid, (expected, traffic_seed_variant) in \
                self.js_split_vectors.items():
            with self.subTest(uid=uid):
                context = self.create_context(
                    self.experiment(50, "exp_split_seed",
                                    [{"type": "split", "percentages": "50/50"}],
                                    split=[1.0, 0.0]),
                    units={"session_id": uid})
                self.assertEqual(expected,
                                 context.get_treatment("exp_split_seed"))
                self.assertTrue(context.exposures[0].ruleOverride)
                context.close()
        # The vectors tell the experiment seeds from the traffic seeds.
        self.assertTrue(any(a != b for a, b in self.js_split_vectors.values()))

    def test_unknown_rule_type_is_skipped(self):
        context = self.create_context(
            self.experiment(51, "exp_unknown_type",
                            [{"name": "future", "type": "future_action",
                              "variant": 0},
                             {"name": "known", "type": "assign",
                              "variant": 1}],
                            split=[1.0, 0.0]),
            self.experiment(52, "exp_healthy", [], split=[0.0, 1.0]))
        self.assertEqual(1, context.get_treatment("exp_unknown_type"))
        self.assertTrue(context.exposures[-1].ruleOverride)
        self.assertEqual(1, context.get_treatment("exp_healthy"))
        self.assertFalse(context.exposures[-1].ruleOverride)
        context.close()

    def test_rule_scope_uses_configured_environment_not_attribute(self):
        # The fixture's configured environment is "production". A user
        # "environment" attribute overlays conditions but not the rule's
        # environments scope.
        scoped = {"name": "prod_only", "type": "assign", "variant": 1,
                  "environments": ["production"]}
        conditioned = {"name": "staging_attr", "type": "assign",
                       "variant": 1,
                       "conditions": {"eq": [{"var": "environment"},
                                             {"value": "staging"}]}}
        staging_scope = {"name": "staging_only", "type": "assign",
                         "variant": 1, "environments": ["staging"]}
        context = self.create_context(
            self.experiment(53, "exp_scope_prod", [scoped], split=[1.0, 0.0]),
            self.experiment(54, "exp_cond_staging", [conditioned],
                            split=[1.0, 0.0]),
            self.experiment(55, "exp_scope_staging", [staging_scope],
                            split=[1.0, 0.0]))
        context.set_attribute("environment", "staging")
        self.assertEqual(1, context.get_treatment("exp_scope_prod"))
        self.assertEqual(1, context.get_treatment("exp_cond_staging"))
        self.assertEqual(0, context.get_treatment("exp_scope_staging"))
        context.close()


class ForwardCompatibilityTest(CrossSdkRuleScenariosTest):
    """Unknown payload fields at every level and any assignmentRules value
    degrade only the experiment that carries them."""

    rules_values = (
        ("omitted", KeyError), ("null", None), ("empty", ""), ("braces", "{}"),
        ("invalid", "{x"), ("object", {"rules": []}), ("number", 5),
        ("bool", True), ("list", [1]), ("rules_not_list", '{"rules":5}'),
        ("bool_type", '{"rules":[{"type":true,"variant":0}]}'),
        ("number_type", '{"rules":[{"type":0,"variant":0}]}'),
        ("unknown_operator", '{"rules":[{"type":"assign","variant":0,'
                             '"conditions":{"future_op":[1]}}]}'),
    )

    def payload(self, rules):
        future = self.experiment(
            1, "exp_future", [], split=[0.0, 1.0],
            futureScalar=1, futureObject={"x": [1]}, futureArray=[{"y": 1}],
            applications=[{"name": "website", "future": {"z": 1}}],
            variants=[{"name": "A", "config": None, "future": [1]},
                      {"name": "B", "config": "{\"k\":1}", "future": {}}],
            customFieldValues=[{"name": "f", "type": "string", "value": "v",
                                "future": 1}],
            holdouts=[{"id": 9, "future": True}], switchback={"future": 1})
        if rules is KeyError:
            del future["assignmentRules"]
        else:
            future["assignmentRules"] = rules
        return future, self.experiment(2, "exp_plain", [], split=[0.0, 1.0])

    def test_unknown_fields_and_rule_values_are_ignored(self):
        for label, rules in self.rules_values:
            with self.subTest(rules=label):
                context = self.create_context(*self.payload(rules))
                self.assertTrue(context.is_ready())
                self.assertFalse(context.is_failed())
                self.assertEqual(1, context.get_treatment("exp_future"))
                self.assertEqual(1, context.get_variable_value("k", 0))
                self.assertEqual("v", context.get_custom_field_value(
                    "exp_future", "f"))
                self.assertEqual(1, context.get_treatment("exp_plain"))
                self.assertEqual([False, False],
                                 [e.ruleOverride for e in context.exposures])
                context.close()

    def test_unknown_root_fields_are_ignored(self):
        content = json.dumps({"experiments": list(self.payload(KeyError)),
                              "futureRoot": {"a": [1]}, "futureFlag": True})
        fixture = SystemAttributesTest()
        fixture.set_up()
        data = fixture.deser.deserialize(
            bytes(content, encoding="utf-8"), 0, len(content))
        self.assertIsNotNone(data)
        self.assertEqual(["exp_future", "exp_plain"],
                         [e.name for e in data.experiments])


class RuleTraversalTest(CrossSdkRuleScenariosTest):

    def test_condition_exception_tries_next_rule(self):
        context = self.create_context(self.experiment(
            60, "exp_throwing_condition",
            [{"name": "boom", "type": "assign", "variant": 0,
              "conditions": {"boom": []}},
             {"name": "next", "type": "assign", "variant": 1}],
            split=[1.0, 0.0]))
        evaluate = context.audience_matcher.json_expr.evaluate_boolean_expr

        def throwing(expr, attributes):
            if "boom" in expr:
                raise RuntimeError("boom")
            return evaluate(expr, attributes)

        context.audience_matcher.json_expr.evaluate_boolean_expr = throwing
        self.assertEqual(1, context.get_treatment("exp_throwing_condition"))
        self.assertTrue(context.exposures[0].ruleOverride)
        context.close()

    def test_rule_wins_over_zero_traffic(self):
        # Scenario 306: a rule is applied even when the unit is outside the
        # experiment's traffic.
        context = self.create_context(self.experiment(
            61, "exp_rule_no_traffic",
            [{"name": "all", "type": "assign", "variant": 1}],
            trafficSplit=[1.0, 0.0]))
        self.assertEqual(1, context.get_treatment("exp_rule_no_traffic"))
        self.assertEqual((1, True, True),
                         (context.exposures[0].variant,
                          context.exposures[0].eligible,
                          context.exposures[0].ruleOverride))
        context.close()
