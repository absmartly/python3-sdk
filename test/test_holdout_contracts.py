"""Holdouts beyond the Java port: the forward-compatible payload, Mapping
and duck-typed inputs, the H1-H8 conformance cases, no cost (and no wire
change) without holdouts, and probes that pin the decisions a mutant would
flip."""
import json
import threading
import types
import unittest
from collections import OrderedDict
from concurrent.futures import Future
from types import MappingProxyType

from sdk import context as context_module
from sdk.context_error import ContextError
from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.json.context_data import ContextData
from sdk.json.experiment import Experiment
from sdk.json.holdout import Holdout
from test.holdout_fixtures import (
    HOLDOUT_A_SEEDS, HOLDOUT_B_SEEDS, NORMAL_VARIANT, THREE_ARM_0_SEEDS,
    THREE_ARM_1_SEEDS, THREE_ARM_2_SEEDS, THREE_ARM_SPLIT, UID,
    UID_NOT_HELD_OUT, UNIT_TYPE, context_data, experiment, holdout,
    three_arm_holdout, with_variables)
from test.test_context_holdouts import HoldoutTestCase, US_RULE

UNKNOWN = {"futureScalar": 1, "futureObject": {"nested": [1, {"x": None}]},
           "futureArray": [{"y": 1}, 2, "z"], "futureNull": None}


class HoldoutForwardCompatibilityTest(HoldoutTestCase):
    """Contract §5: unknown keys at every level of a holdout payload are
    ignored and degrade nothing."""

    def payload(self):
        held = dict(self.holdout_a(), **UNKNOWN)
        held["variants"] = [dict(v, future={"a": 1}) for v in held["variants"]]
        held["futureHoldoutRule"] = {"type": "future", "conditions": [1]}
        other = dict(holdout(12, "holdout_b", HOLDOUT_B_SEEDS,
                             holdoutType="future_type"), **UNKNOWN)
        covered = dict(self.covered(1, "exp_covered", [11]), **UNKNOWN)
        second = dict(self.covered(2, "exp_second", [12]), **UNKNOWN)
        content = json.dumps({"experiments": [covered, second],
                              "holdouts": [held, other],
                              "futureRoot": {"holdouts": [1]},
                              "futureHoldoutsV2": [{"id": 11}]})
        return content

    def test_unknown_keys_inside_holdout_objects_are_ignored(self):
        content = self.payload()
        data = DefaultContextDataDeserializer().deserialize(
            bytes(content, "utf-8"), 0, len(content))
        self.assertIsNotNone(data)
        context = self.create_context(data)
        self.assertTrue(context.is_ready())
        self.assertFalse(context.is_failed())
        self.assertEqual(0, context.get_treatment("exp_covered"))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_second"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0),
            self.exposure(2, "exp_second", NORMAL_VARIANT),
            self.holdout_exposure(12, "holdout_b", 1))
        self.assertEqual([], [e for e in self.logger.events
                              if e[0].name == "ERROR"])

    def test_malformed_holdouts_value_disables_only_holdouts(self):
        for label, value in (("object", {"id": 11}), ("number", 5),
                             ("string", "holdouts"), ("bool", True),
                             ("mixed", [None, 5, "x", [1], True,
                                        {"id": "11", "split": [0.1, 0.9]},
                                        {"id": 11, "split": "bad"},
                                        {"id": 11, "split": [True, 0.9]},
                                        {"id": 11, "split": [0.1, 0.9],
                                         "seedHi": "13"}])):
            with self.subTest(holdouts=label):
                context = self.create_context(context_data(
                    [self.covered(1, "exp_covered", [11]),
                     experiment(2, "exp_plain")], value))
                self.assertFalse(context.is_failed())
                self.assertEqual(NORMAL_VARIANT,
                                 context.get_treatment("exp_covered"))
                self.assertEqual(NORMAL_VARIANT,
                                 context.get_treatment("exp_plain"))
                self.assertEqual(2, context.get_pending_count())

    def test_malformed_holdout_ids_mean_not_covered(self):
        for label, value in (("number", 11), ("string", "11"),
                             ("object", {"11": True}), ("null", None),
                             ("strings", ["11"]), ("bools", [True]),
                             ("fraction", [11.5])):
            with self.subTest(holdout_ids=label):
                exp = experiment(1, "exp_covered")
                exp["holdoutIds"] = value
                context = self.create_context(context_data(
                    [exp], [self.holdout_a(id=1)] if label == "bools"
                    else [self.holdout_a()]))
                self.assertEqual(NORMAL_VARIANT,
                                 context.get_treatment("exp_covered"))
                self.assertEqual(1, context.get_pending_count())

    def test_integral_float_ids_are_ids(self):
        exp = experiment(1, "exp_covered")
        exp["holdoutIds"] = [11.0]
        context = self.create_context(context_data(
            [exp], [dict(self.holdout_a(), id=11.0)]))
        self.assertEqual(0, context.get_treatment("exp_covered"))
        self.assert_published(context,
                              self.holdout_exposure(11, "holdout_a", 0))

    def test_duplicate_holdout_entries_keep_the_last_like_js(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_covered", [11])],
            [holdout(11, "first", HOLDOUT_B_SEEDS),
             holdout(11, "last", HOLDOUT_A_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_covered"))
        self.assert_published(context, self.holdout_exposure(11, "last", 0))

    def test_holdout_fields_round_trip_through_the_deserializer(self):
        data = context_data([self.covered(1, "exp", [11, 12])],
                            [self.holdout_a()])
        self.assertEqual([11, 12], data.experiments[0].holdoutIds)
        self.assertEqual(11, data.holdouts[0]["id"])
        self.assertEqual("full", data.holdouts[0]["holdoutType"])


class HoldoutInputTypesTest(HoldoutTestCase):
    """Holdouts given as any Mapping, Holdout objects or duck-typed
    objects, on hand-built ContextData."""

    def hand_built(self, holdouts, holdout_ids=(11,)):
        exp = Experiment()
        for key, value in experiment(1, "exp_covered").items():
            if key not in ("variants", "applications"):
                setattr(exp, key, value)
        variant = types.SimpleNamespace(name="A", config=None)
        exp.variants = [variant, types.SimpleNamespace(name="B", config=None)]
        exp.holdoutIds = holdout_ids
        data = ContextData()
        data.experiments = [exp]
        data.holdouts = holdouts
        return data

    def assert_held_out(self, data):
        context = self.create_context(data)
        self.assertEqual(0, context.get_treatment("exp_covered"))
        self.assert_published(context,
                              self.holdout_exposure(11, "holdout_a", 0))

    def test_mapping_inputs(self):
        source = self.holdout_a()
        for label, entry in (("dict", dict(source)),
                             ("ordered", OrderedDict(source)),
                             ("proxy", MappingProxyType(dict(source)))):
            with self.subTest(entry=label):
                self.set_up_fixture()
                self.assert_held_out(self.hand_built((entry,)))

    def test_holdout_model_and_duck_typed_objects(self):
        model = Holdout()
        model.id, model.name, model.iteration = 11, "holdout_a", 1
        model.seedHi, model.seedLo = HOLDOUT_A_SEEDS
        model.split = [0.1, 0.9]
        self.assert_held_out(self.hand_built([model]))

        self.set_up_fixture()
        duck = types.SimpleNamespace(id=11, name="holdout_a", iteration=1,
                                     seedHi=HOLDOUT_A_SEEDS[0],
                                     seedLo=HOLDOUT_A_SEEDS[1],
                                     split=(0.1, 0.9))
        self.assert_held_out(self.hand_built([duck], holdout_ids=[11]))

    def test_missing_seeds_default_to_zero(self):
        # A Holdout object leaves unset seeds at 0, like the Java model.
        duck = types.SimpleNamespace(id=11, name="holdout_a", iteration=1,
                                     split=[0.1, 0.9])
        context = self.create_context(self.hand_built([duck]))
        context.get_treatment("exp_covered")
        expected = context.get_variant_assigner(
            UNIT_TYPE, context.get_unit_hash(UNIT_TYPE, UID)).assign(
                [0.1, 0.9], 0, 0)
        self.assertEqual(expected,
                         context._holdout_assignments[(11, UNIT_TYPE)].variant)

    def test_legacy_context_data_and_experiments_without_the_new_fields(self):
        # Duck-typed data objects from before holdouts (no holdouts or
        # holdoutIds attributes at all) still work.
        exp = types.SimpleNamespace(**{
            k: v for k, v in experiment(1, "exp_legacy").items()
            if k != "variants"})
        exp.variants = [types.SimpleNamespace(name="A", config=None),
                        types.SimpleNamespace(name="B", config=None)]
        exp.customFieldValues = None
        exp.assignmentRules = None
        data = types.SimpleNamespace(experiments=[exp])
        context = self.create_context(data)
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_legacy"))

    def test_new_model_fields_default_to_none(self):
        self.assertIsNone(ContextData().holdouts)
        self.assertIsNone(Experiment().holdoutIds)
        self.assertIsNone(Experiment().holdoutType)
        self.assertEqual((0, None, None, 0, 0, 0, None, None),
                         (Holdout.id, Holdout.name, Holdout.unitType,
                          Holdout.iteration, Holdout.seedHi, Holdout.seedLo,
                          Holdout.split, Holdout.holdoutType))


class HoldoutConformanceTest(HoldoutTestCase):
    """cross-sdk-tests H1-H8 and the lifecycle scenarios 223-227."""

    def test_h1_duplicate_holdout_ids_fire_one_exposure(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_dup", [11, 11, 11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_dup"))
        self.assertEqual(1, len(context.get_assignment("exp_dup").holdouts))
        self.assert_published(context,
                              self.holdout_exposure(11, "holdout_a", 0))

    def test_h1_duplicate_holdout_ids_are_sorted(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_dup", [12, 11, 12])],
                         [self.holdout_b(), self.holdout_a()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        context.get_treatment("exp_dup")
        self.assertEqual([("exp_dup", 0), ("holdout_a", 1), ("holdout_b", 1)],
                         [(e.name, e.variant) for e in context.exposures])

    def test_h2_holdout_without_split_is_ignored(self):
        for label, change in (("missing", None), ("null", {"split": None}),
                              ("empty", {"split": []})):
            with self.subTest(split=label):
                entry = self.holdout_a()
                if change is None:
                    del entry["split"]
                else:
                    entry.update(change)
                context = self.create_context(context_data(
                    [self.covered(1, "exp_h2", [11])], [entry]))
                self.assertEqual(NORMAL_VARIANT,
                                 context.get_treatment("exp_h2"))
                self.assertEqual(["exp_h2"],
                                 [e.name for e in context.exposures])

    def test_h3_same_iteration_seed_or_split_change_does_not_rerandomize(self):
        for label, change in (("seed", {"seedHi": HOLDOUT_B_SEEDS[0],
                                        "seedLo": HOLDOUT_B_SEEDS[1]}),
                              ("split", {"split": [0.0, 1.0]})):
            with self.subTest(change=label):
                context = self.create_context(context_data(
                    [self.covered(1, "exp_h3", [11])], [self.holdout_a()]))
                self.assertEqual(0, context.get_treatment("exp_h3"))
                self.refresh(context, context_data(
                    [self.covered(1, "exp_h3", [11])],
                    [dict(self.holdout_a(), **change)]))
                self.assertEqual(0, context.get_treatment("exp_h3"))
                self.assertEqual(1, context.get_pending_count())

    def test_h4_peek_queues_no_holdout_exposure(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_h4", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.peek_treatment("exp_h4"))
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual([], self.exposure_events())
        self.assertEqual(0, context.get_treatment("exp_h4"))
        self.assertEqual(1, context.get_pending_count())

    def test_h6_two_unit_types_sharing_a_holdout_publish_two_exposures(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_session", [11]),
             self.covered(2, "exp_user", [11], unit_type="user_id")],
            [self.holdout_a()]),
            units={UNIT_TYPE: UID, "user_id": UID_NOT_HELD_OUT})
        self.assertEqual(0, context.get_treatment("exp_session"))
        self.assertEqual(0, context.get_treatment("exp_user"))
        self.assertEqual(
            [(11, UNIT_TYPE, 0), (2, "user_id", 0), (11, "user_id", 1)],
            [(e.id, e.unit, e.variant) for e in context.exposures])

    def test_h7_strict_audience_mismatch_on_not_held_out_experiment_fires_holdout(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_h7", [11], audienceStrict=True,
                                       audience=json.dumps({"filter": [
                                           {"gte": [{"var": "age"},
                                                    {"value": 20}]}]}))],
                         [self.holdout_a()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        context.set_attribute("age", 5)
        self.assertEqual(0, context.get_treatment("exp_h7"))
        self.assertEqual(
            [self.exposure(1, "exp_h7", 0, assigned=False,
                           audience_mismatch=True),
             self.holdout_exposure(11, "holdout_a", 1)],
            self.exposure_tuples(context.exposures))

    def test_h8_shared_key_assigned_second_candidate_wins_and_both_holdouts_fire(self):
        context = self.create_context(context_data(
            [with_variables(self.covered(1, "exp_first", [11]), "color"),
             with_variables(self.covered(2, "exp_second", [12]), "color")],
            [self.holdout_a(), self.holdout_b()]))
        self.assertEqual("treatment",
                         context.get_variable_value("color", "default"))
        self.assertEqual(
            [self.holdout_exposure(11, "holdout_a", 0),
             self.exposure(2, "exp_second", NORMAL_VARIANT),
             self.holdout_exposure(12, "holdout_b", 1)],
            self.exposure_tuples(context.exposures))

    def test_223_exposure_state_survives_publish(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_223", [11])], [self.holdout_a()]))
        context.get_treatment("exp_223")
        context.publish()
        context.get_treatment("exp_223")
        self.assertEqual(0, context.get_pending_count())

    def test_225_refresh_adding_or_removing_coverage_re_resolves(self):
        context = self.create_context(context_data(
            [experiment(1, "exp_225")], [self.holdout_a()]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_225"))
        self.refresh(context, context_data(
            [self.covered(1, "exp_225", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_225"))
        self.refresh(context, context_data(
            [experiment(1, "exp_225")], [self.holdout_a()]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_225"))
        self.assertEqual(
            [("exp_225", 1), ("holdout_a", 0), ("exp_225", 1)],
            [(e.name, e.variant) for e in context.exposures])

    def test_226_suppressed_variable_value_is_control_not_default(self):
        context = self.create_context(context_data(
            [with_variables(self.covered(1, "exp_226", [11]), "color")],
            [self.holdout_a()]))
        self.assertEqual("control",
                         context.get_variable_value("color", "default"))
        self.assertEqual("control",
                         context.peek_variable_value("color", "default"))
        self.assertEqual("default",
                         context.get_variable_value("missing", "default"))

    def test_226_first_suppressed_candidate_is_the_fallback_even_without_the_key(self):
        first = self.covered(1, "exp_first", [11])
        first["variants"] = [{"name": "A", "config": '{"other":"x"}'},
                             {"name": "B", "config": '{"color":"b1"}'}]
        second = with_variables(self.covered(2, "exp_second", [11]), "color")
        context = self.create_context(context_data(
            [first, second], [self.holdout_a()]))
        self.assertEqual("default",
                         context.get_variable_value("color", "default"))

    def test_227_holdout_uses_covered_experiment_unit_type(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_227", [11])],
                         [holdout(11, "holdout_a", HOLDOUT_A_SEEDS,
                                  unit_type="user_id")]),
            units={UNIT_TYPE: UID, "user_id": UID_NOT_HELD_OUT})
        self.assertEqual(0, context.get_treatment("exp_227"))
        self.assertEqual([(11, UNIT_TYPE, 0)],
                         [(e.id, e.unit, e.variant) for e in context.exposures])


class NoHoldoutCostTest(HoldoutTestCase):
    """A payload without holdouts takes the pre-holdout paths and publishes
    the same bytes."""

    BASELINE = (
        b'{"attributes": [{"name": "age", "setAt": 1620000000000, '
        b'"value": 5}], "exposures": [{"assigned": true, "audienceMismatch": '
        b'false, "custom": false, "eligible": true, "exposedAt": '
        b'1620000000000, "fullOn": false, "id": 1, "name": "exp_plain", '
        b'"overridden": false, "ruleOverride": false, "unit": "session_id", '
        b'"variant": 1}, {"assigned": true, "audienceMismatch": false, '
        b'"custom": false, "eligible": true, "exposedAt": 1620000000000, '
        b'"fullOn": true, "id": 2, "name": "exp_fullon", "overridden": '
        b'false, "ruleOverride": false, "unit": "session_id", "variant": 1}, '
        b'{"assigned": false, "audienceMismatch": false, "custom": false, '
        b'"eligible": true, "exposedAt": 1620000000000, "fullOn": false, '
        b'"id": 3, "name": "exp_override", "overridden": true, '
        b'"ruleOverride": false, "unit": "session_id", "variant": 1}], '
        b'"hashed": true, "historic": false, "publishedAt": 1620000000000, '
        b'"units": [{"type": "session_id", "uid": '
        b'"pAE3a1i5Drs5mKRNq56adA"}]}')

    def experiments(self):
        return [experiment(1, "exp_plain"),
                experiment(2, "exp_fullon", full_on_variant=1),
                experiment(3, "exp_override")]

    def publish_bytes(self, data):
        self.set_up_fixture()
        context = self.create_context(data, overrides={"exp_override": 1})
        context.set_attribute("age", 5)
        for name in ("exp_plain", "exp_fullon", "exp_override",
                     "exp_plain"):
            context.get_treatment(name)
        return self.serialized(self.publish(context))

    def test_publish_bytes_without_holdouts_are_unchanged(self):
        for label, data in (
                ("no key", context_data(self.experiments())),
                ("null", context_data(self.experiments(), None)),
                ("empty", context_data(self.experiments(), [])),
                ("unused holdout", context_data(self.experiments(),
                                                [self.holdout_a()]))):
            with self.subTest(payload=label):
                self.assertEqual(self.BASELINE, self.publish_bytes(data))

    def test_no_holdout_state_is_built_without_holdouts(self):
        context = self.create_context(context_data(self.experiments()))
        for name in ("exp_plain", "exp_fullon"):
            context.get_treatment(name)
            assignment = context.get_assignment(name)
            self.assertIsNone(assignment.holdouts)
            self.assertIsNone(assignment.holdout_assignments)
            self.assertFalse(assignment.suppressed)
        self.assertEqual({}, context._holdouts_by_id)
        self.assertEqual({}, context._holdout_assignments)
        self.assertTrue(all(e.holdouts is None
                            for e in context.index.values()))

    def test_cached_read_without_holdouts_never_touches_holdout_code(self):
        context = self.create_context(context_data(self.experiments()))
        context.get_treatment("exp_plain")
        calls = []
        originals = {}
        for name in ("_holdout_set_matches", "_is_held_out_by",
                     "_applicable_holdouts"):
            originals[name] = getattr(context_module, name)
            setattr(context_module, name,
                    lambda *a, _n=name, **k: calls.append(_n))
        self.addCleanup(lambda: [setattr(context_module, n, f)
                                 for n, f in originals.items()])
        for _ in range(3):
            context.get_treatment("exp_plain")
            context.peek_treatment("exp_fullon")
        self.assertEqual([], calls)


class HoldoutMutationProbeTest(HoldoutTestCase):
    """Each probe fails under a specific mutant of the holdout logic."""

    def test_is_held_out_by_truth_table(self):
        cases = [
            # (variant, arm count, fullOnVariant) -> held out
            ((0, 2, 0), True), ((0, 2, 1), True), ((0, 3, 0), True),
            ((0, 3, 2), True), ((1, 2, 0), False), ((1, 2, 1), False),
            ((1, 3, 0), True), ((1, 3, 2), False), ((2, 3, 0), False),
            ((2, 3, 2), False), ((1, 4, 0), False), ((1, 1, 0), False),
            ((3, 4, 0), False)]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertIs(expected, context_module._is_held_out_by(*args))

    def test_arity_comes_from_split_not_holdout_type(self):
        # Scenario 222: a 3-entry split is 3-arm whatever holdoutType says,
        # and a 2-entry split is 2-arm even when labelled all_full_on.
        for holdout_type in (None, "full", "all_full_on", "future"):
            with self.subTest(holdout_type=holdout_type):
                three = three_arm_holdout(21, "holdout_three",
                                          THREE_ARM_1_SEEDS)
                three["holdoutType"] = holdout_type
                context = self.create_context(context_data(
                    [self.covered(1, "exp_non_fullon", [21])], [three]))
                self.assertEqual(0, context.get_treatment("exp_non_fullon"))

                self.set_up_fixture()
                two = holdout(21, "holdout_two", HOLDOUT_B_SEEDS,
                              holdout_type=holdout_type or "all_full_on")
                context = self.create_context(context_data(
                    [self.covered(1, "exp_non_fullon", [21])], [two]))
                self.assertEqual(NORMAL_VARIANT,
                                 context.get_treatment("exp_non_fullon"))

    def test_union_requires_every_holdout_to_be_checked(self):
        # Held out only by the last of three holdouts.
        context = self.create_context(context_data(
            [self.covered(1, "exp_union", [11, 12, 13])],
            [holdout(11, "h11", HOLDOUT_B_SEEDS),
             three_arm_holdout(12, "h12", THREE_ARM_2_SEEDS),
             holdout(13, "h13", HOLDOUT_A_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_union"))
        self.assertEqual([("h11", 1), ("h12", 2), ("h13", 0)],
                         [(e.name, e.variant) for e in context.exposures])

    def test_union_is_not_an_intersection(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_union", [11, 12])],
            [holdout(11, "h11", HOLDOUT_A_SEEDS),
             holdout(12, "h12", HOLDOUT_B_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_union"))

    def test_rule_beats_suppression_for_assign_and_split_and_variables(self):
        rules = {
            "assign": US_RULE,
            "split": json.dumps({"rules": [{"type": "split",
                                            "percentages": "0/100"}]})}
        for label, rule in rules.items():
            with self.subTest(rule=label):
                self.set_up_fixture()
                context = self.create_context(
                    context_data([with_variables(
                        self.covered(1, "exp_rule", [11],
                                     assignmentRules=rule), "color")],
                        [self.holdout_a()]),
                    attributes={"country": "US"})
                self.assertEqual("treatment",
                                 context.get_variable_value("color", "x"))
                self.assertEqual(1, context.get_treatment("exp_rule"))
                assignment = context.get_assignment("exp_rule")
                self.assertTrue(assignment.suppressed)
                self.assertTrue(assignment.rule_override)
                self.assertEqual(
                    [self.exposure(1, "exp_rule", 1, assigned=False,
                                   rule_override=True),
                     self.holdout_exposure(11, "holdout_a", 0)],
                    self.exposure_tuples(context.exposures))

    def test_holdout_arm_uses_the_holdout_seeds_and_split(self):
        # Swapping in the experiment's seeds or split would land UID in
        # arm 1 of holdout A.
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_a()]))
        context.get_treatment("exp")
        cached = context._holdout_assignments[(11, UNIT_TYPE)]
        self.assertEqual((0, 2, 1, "holdout_a"),
                         (cached.variant, cached.holdout_arm_count,
                          cached.iteration, cached.name))
        assigner = context.get_variant_assigner(
            UNIT_TYPE, context.get_unit_hash(UNIT_TYPE, UID))
        # The experiment's seeds would put UID in arm 1.
        self.assertEqual(1, assigner.assign([0.1, 0.9], 100, 200))

    def test_suppression_skips_full_on_traffic_and_custom(self):
        for label, fields, custom in (
                ("full on", {"fullOnVariant": 1}, None),
                ("no traffic", {"trafficSplit": [1.0, 0.0]}, None),
                ("custom", {}, {"exp": 1})):
            with self.subTest(case=label):
                self.set_up_fixture()
                context = self.create_context(
                    context_data([self.covered(1, "exp", [11], **fields)],
                                 [self.holdout_a()]),
                    custom_assignments=custom)
                self.assertEqual(0, context.get_treatment("exp"))
                assignment = context.get_assignment("exp")
                self.assertEqual((False, True, False, False),
                                 (assignment.assigned, assignment.eligible,
                                  assignment.full_on, assignment.custom))
                self.assertEqual(["holdout_a"],
                                 [e.name for e in context.exposures])

    def test_iteration_bump_re_exposes_holdout_once(self):
        # Scenario 224.
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_b(id=11)]))
        context.get_treatment("exp")
        self.refresh(context, context_data(
            [self.covered(1, "exp", [11])],
            [dict(self.holdout_b(id=11), iteration=2)]))
        context.get_treatment("exp")
        context.get_treatment("exp")
        self.assertEqual([("exp", 1), ("holdout_b", 1), ("exp", 1),
                          ("holdout_b", 1)],
                         [(e.name, e.variant) for e in context.exposures])

    def test_holdout_exposure_is_named_from_the_pinned_snapshot(self):
        # JS publishes holdouts[i].data.name from the covering experiment's
        # snapshot: a same-iteration rename before the first exposure wins.
        context = self.create_context(context_data(
            [self.covered(1, "exp_a", [11])], [self.holdout_b(id=11)]))
        context.peek_treatment("exp_a")
        self.refresh(context, context_data(
            [self.covered(1, "exp_a", [11]), self.covered(2, "exp_b", [11])],
            [self.holdout_b(id=11, name="renamed")]))
        context.get_treatment("exp_b")
        self.assertEqual(["exp_b", "renamed"],
                         [e.name for e in context.exposures])

    def test_exposure_carries_the_treatment_exposed_at(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_b(id=11)]))
        context.get_treatment("exp", exposed_at=1234)
        self.assertEqual([1234, 1234],
                         [e.exposedAt for e in context.exposures])

    def test_three_arm_matches_scenario_vectors(self):
        for seeds, arm in ((THREE_ARM_0_SEEDS, 0), (THREE_ARM_1_SEEDS, 1),
                           (THREE_ARM_2_SEEDS, 2)):
            context = self.create_context(context_data(
                [self.covered(1, "exp", [21])],
                [holdout(21, "h", seeds, split=THREE_ARM_SPLIT)]))
            context.get_treatment("exp")
            self.assertEqual(arm,
                             context._holdout_assignments[(21, UNIT_TYPE)]
                             .variant)

    def test_retire_and_expose_are_exclusive(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_a()]))
        assignment = context.get_assignment("exp")
        self.assertTrue(context._expose(assignment))
        self.assertFalse(context._retire(assignment))
        other = context.get_assignment("exp")
        self.assertIs(assignment, other)


if __name__ == "__main__":
    unittest.main()


class HoldoutLifecycleRaceTest(HoldoutTestCase):
    """Interleavings of a read with refresh, another reader and close."""

    def test_refresh_between_experiment_and_holdout_lookup_keeps_one_payload(self):
        # Old payload: an ordinary experiment in arm 2 (normal path, 1).
        # New payload: full-on variant 1, holdout iteration 2 in arm 1
        # (full-on experiments are not held out by arm 1, so also 1).
        old = context_data(
            [self.covered(1, "exp_epoch", [21])],
            [three_arm_holdout(21, "h", THREE_ARM_2_SEEDS)])
        new = context_data(
            [self.covered(1, "exp_epoch", [21], full_on_variant=1)],
            [three_arm_holdout(21, "h", THREE_ARM_1_SEEDS, iteration=2)])
        for data in (old, new):
            self.set_up_fixture()
            self.assertEqual(1, self.create_context(data).peek_treatment(
                "exp_epoch"))

        self.set_up_fixture()
        context = self.create_context(old)
        original = context._get_resolution_state

        def refresh_after_read(name):
            state = original(name)
            context.set_data(new)
            return state

        context._get_resolution_state = refresh_after_read
        assignment = context.get_assignment("exp_epoch")
        context._get_resolution_state = original
        self.assertEqual(1, assignment.variant)
        self.assertEqual(assignment.holdouts[0].iteration,
                         assignment.holdout_assignments[0].iteration)
        # The stale resolution does not cache its arm over the installed
        # payload's; the next read resolves the new payload.
        self.assertNotIn((21, UNIT_TYPE), context._holdout_assignments)
        self.assertEqual(1, context.get_treatment("exp_epoch"))
        self.assertEqual([("exp_epoch", 1, True), ("h", 1, False)],
                         [(e.name, e.variant, e.fullOn)
                          for e in context.exposures])

    def test_concurrent_snapshots_publish_their_own_holdout_name(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_a", [11])],
            [self.holdout_b(id=11, name="old")]))
        first = context.get_assignment("exp_a", exposed_at=100)
        self.refresh(context, context_data(
            [self.covered(1, "exp_a", [11]), self.covered(2, "exp_b", [11])],
            [self.holdout_b(id=11, name="new")]))
        second = context.get_assignment("exp_b", exposed_at=200)
        self.assertIs(first.holdout_assignments[0],
                      second.holdout_assignments[0])
        # B's snapshot names the holdout "new"; the shared holdout
        # assignment (resolved under "old") is not where the name comes from.
        self.assertTrue(context._expose(second))
        self.assertTrue(context._expose(first))
        self.assertEqual([("exp_b", 200), ("new", 200), ("exp_a", 100)],
                         [(e.name, e.exposedAt) for e in context.exposures])
        self.assertEqual("old", first.holdout_assignments[0].name)

    def test_threads_exposing_two_snapshots_publish_one_consistent_holdout(self):
        for _ in range(50):
            self.set_up_fixture()
            context = self.create_context(context_data(
                [self.covered(1, "exp_a", [11])],
                [self.holdout_b(id=11, name="old")]))
            a = context.get_assignment("exp_a", exposed_at=100)
            self.refresh(context, context_data(
                [self.covered(1, "exp_a", [11]),
                 self.covered(2, "exp_b", [11])],
                [self.holdout_b(id=11, name="new")]))
            b = context.get_assignment("exp_b", exposed_at=200)
            barrier = threading.Barrier(2)

            def expose(assignment):
                barrier.wait()
                context._expose(assignment)

            threads = [threading.Thread(target=expose, args=(x,))
                       for x in (a, b)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            holdout = [(e.name, e.exposedAt) for e in context.exposures
                       if e.id == 11]
            self.assertIn(holdout, ([("old", 100)], [("new", 200)]))

    def test_failed_close_between_own_and_holdout_exposure_keeps_holdout_retryable(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_close", [11])], [self.holdout_b(id=11)]))
        failing = Future()
        self.client.publish_results.append(failing)
        closing = []
        original = context._accept_exposure

        workers = []

        def close_between(assignment, name, exposed_at):
            # Another thread closes right after the experiment's own
            # exposure is accepted; it must wait for the holdout's.
            exposure = original(assignment, name, exposed_at)
            if not workers:
                worker = threading.Thread(
                    target=lambda: closing.append(context.close_async()))
                workers.append(worker)
                worker.start()
                worker.join(0.2)
            return exposure

        context._accept_exposure = close_between
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_close"))
        context._accept_exposure = original
        workers[0].join(5)
        self.assertFalse(workers[0].is_alive())
        self.client.wait_for_publish(1)
        self.assertEqual([("exp_close", 1), ("holdout_b", 1)],
                         [(e.name, e.variant)
                          for e in self.client.published[0].exposures])
        failing.set_exception(RuntimeError("publish failed"))
        with self.assertRaises(RuntimeError):
            closing[0].result(5)
        self.assertFalse(context.is_closed())
        # Both exposures are back in the queue; a later read adds none.
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_close"))
        self.assertEqual([("exp_close", 1), ("holdout_b", 1)],
                         [(e.name, e.variant) for e in context.exposures])

    def test_close_rejects_the_whole_exposure_group(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_close", [11])], [self.holdout_b(id=11)]))
        assignment = context.get_assignment("exp_close")
        context.closing.set(True)
        with self.assertRaises(ContextError):
            context._expose(assignment)
        self.assertFalse(assignment.exposed.value)
        self.assertFalse(assignment.holdout_assignments[0].exposed.value)
        self.assertEqual([], context.exposures)
        context.closing.set(False)
        self.assertTrue(context._expose(assignment))
        self.assertEqual(2, context.get_pending_count())

    def test_holdout_exposure_reuses_the_experiment_exposure_time(self):
        times = iter([111, 222, 333])
        self.clock.millis = lambda: next(times)
        context = self.create_context(context_data(
            [self.covered(1, "exp_time", [11])], [self.holdout_b(id=11)]))
        context.get_treatment("exp_time")
        self.assertEqual([111, 111],
                         [e.exposedAt for e in context.exposures])


class HoldoutRevalidationTest(HoldoutTestCase):

    def test_refresh_with_split_change_same_iteration_does_not_re_expose(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_split_edit", [11])],
                         [self.holdout_a()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        context.get_treatment("exp_split_edit")
        self.assertEqual(2, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_split_edit", [11])],
            [holdout(11, "holdout_a", HOLDOUT_A_SEEDS, split=[0.05, 0.95])]))
        context.get_treatment("exp_split_edit")
        self.assertEqual(2, context.get_pending_count())
        # A rename makes a new snapshot, so the (id, iteration) comparison
        # itself must ignore the split.
        self.refresh(context, context_data(
            [self.covered(1, "exp_split_edit", [11])],
            [holdout(11, "renamed", HOLDOUT_A_SEEDS, split=[0.2, 0.8])]))
        context.get_treatment("exp_split_edit")
        self.assertEqual(2, context.get_pending_count())

    def test_refresh_between_cache_check_and_revalidation_rebuilds_on_iteration_bump(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_rv", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.peek_treatment("exp_rv"))
        # A new attribute sends the next read through the write-lock
        # revalidation; the refresh lands between the two checks.
        context.set_attribute("country", "US")
        original = context._get_experiment_state

        def refresh_after_read(name):
            state = original(name)
            context._get_experiment_state = original
            context.set_data(context_data(
                [self.covered(1, "exp_rv", [11])],
                [holdout(11, "holdout_a", HOLDOUT_B_SEEDS, iteration=2)]))
            return state

        context._get_experiment_state = refresh_after_read
        assignment = context.get_assignment("exp_rv")
        self.assertEqual(2, assignment.holdouts[0].iteration)
        self.assertEqual(NORMAL_VARIANT, assignment.variant)

    def test_installing_data_without_holdouts_never_matches_holdouts(self):
        calls = []
        original = context_module._applicable_holdouts

        def counting(*args):
            calls.append(args)
            return original(*args)

        context_module._applicable_holdouts = counting
        self.addCleanup(setattr, context_module, "_applicable_holdouts",
                        original)
        for holdouts in (None, [], [{"id": 11}]):
            context = self.create_context(context_data(
                [self.covered(1, "exp", [11]), experiment(2, "exp_2")],
                holdouts))
            self.refresh(context, context_data([experiment(1, "exp")],
                                               holdouts))
            context.get_treatment("exp")
        self.assertEqual([], calls)
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_a()]))
        self.assertEqual(1, len(calls))


class SuppressedFallbackTest(HoldoutTestCase):
    """JS _resolveVariableValue: only a held-out candidate that neither an
    override nor a rule decided becomes the control-value fallback."""

    def two_candidates(self, first_fields=None, overrides=None):
        first = self.covered(1, "exp_first", [11], **(first_fields or {}))
        first["variants"] = [{"name": "A", "config": '{"other":"x"}'},
                             {"name": "B", "config": '{"color":"b1"}'}]
        second = with_variables(self.covered(2, "exp_second", [11]), "color")
        return self.create_context(
            context_data([first, second], [self.holdout_a()]),
            overrides=overrides)

    def test_overridden_held_out_candidate_is_not_the_fallback(self):
        context = self.two_candidates(overrides={"exp_first": 0})
        self.assertEqual("control",
                         context.peek_variable_value("color", "default"))
        self.assertEqual("control",
                         context.get_variable_value("color", "default"))

    def test_rule_won_held_out_candidate_is_not_the_fallback(self):
        rule = json.dumps({"rules": [{"type": "assign", "variant": 0}]})
        context = self.two_candidates({"assignmentRules": rule})
        self.assertTrue(context.get_assignment("exp_first").rule_override)
        self.assertEqual("control",
                         context.peek_variable_value("color", "default"))
        self.assertEqual("control",
                         context.get_variable_value("color", "default"))

    def test_held_out_assignment_rechecks_the_audience_once_like_js(self):
        # JS audienceMatches runs for a held-out assignment too; a changed
        # result rebuilds it once, then the new attrs_seq keeps it cached.
        context = self.create_context(context_data(
            [self.covered(1, "exp_aud", [11], audience=json.dumps(
                {"filter": [{"eq": [{"var": "country"},
                                    {"value": "US"}]}]}))],
            [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_aud"))
        first = context.get_assignment("exp_aud")
        calls = []
        evaluate = context.audience_matcher.evaluate
        context.audience_matcher.evaluate = \
            lambda *args: calls.append(args) or evaluate(*args)
        context.set_attribute("country", "GB")
        for _ in range(3):
            self.assertEqual(0, context.get_treatment("exp_aud"))
        self.assertEqual(1, len(calls))
        self.assertIsNot(first, context.get_assignment("exp_aud"))
        self.assertEqual([("holdout_a", 0)],
                         [(e.name, e.variant) for e in context.exposures])

    def test_rebuilt_held_out_assignment_publishes_the_renamed_holdout(self):
        # Parity with JS: peek, an attribute change and a same-iteration
        # rename; the next treatment rebuilds from the new payload.
        audience = json.dumps({"filter": [{"eq": [{"var": "country"},
                                                  {"value": "US"}]}]})
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11], audience=audience)],
            [self.holdout_a(name="h4")]))
        self.assertEqual(0, context.peek_treatment("exp"))
        context.set_attribute("country", "GB")
        self.refresh(context, context_data(
            [self.covered(1, "exp", [11], audience=audience)],
            [self.holdout_a(name="h4x")]))
        self.assertEqual(0, context.get_treatment("exp"))
        self.assertEqual([("h4x", 0)],
                         [(e.name, e.variant) for e in context.exposures])


class HoldoutRefreshCostTest(HoldoutTestCase):

    def test_cached_reads_match_the_holdout_set_by_identity_after_refresh(self):
        payload = context_data([self.covered(1, "exp", [11])],
                               [self.holdout_b(id=11)])
        context = self.create_context(payload)
        context.get_treatment("exp")
        self.refresh(context, context_data(
            [self.covered(1, "exp", [11])],
            [self.holdout_b(id=11, seedHi=99)]))
        calls = []
        original = context_module._holdout_set_matches
        context_module._holdout_set_matches = \
            lambda *args: calls.append(args) or original(*args)
        self.addCleanup(setattr, context_module, "_holdout_set_matches",
                        original)
        for _ in range(5):
            self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp"))
        self.assertEqual([], calls)

    def test_renamed_or_bumped_holdout_gets_a_new_snapshot(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_b(id=11)]))
        before = context.get_experiment("exp").holdouts
        for change in ({"name": "renamed"}, {"iteration": 2}):
            self.refresh(context, context_data(
                [self.covered(1, "exp", [11])],
                [dict(self.holdout_b(id=11), **change)]))
            after = context.get_experiment("exp").holdouts
            self.assertIsNot(before, after)
            before = after

    def test_refresh_appending_a_holdout_publishes_it(self):
        context = self.create_context(
            context_data([self.covered(1, "exp", [11])],
                         [self.holdout_a(), self.holdout_b()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        self.refresh(context, context_data(
            [self.covered(1, "exp", [11, 12])],
            [self.holdout_a(), self.holdout_b()]))
        context.get_treatment("exp")
        self.assertEqual(["exp", "holdout_a", "holdout_b"],
                         [e.name for e in context.exposures])

    def test_refresh_dropping_the_last_holdout_stops_publishing_it(self):
        context = self.create_context(
            context_data([self.covered(1, "exp", [11, 12])],
                         [self.holdout_a(), self.holdout_b()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        self.refresh(context, context_data(
            [self.covered(1, "exp", [11])],
            [self.holdout_a(), self.holdout_b()]))
        context.get_treatment("exp")
        self.assertEqual(["exp", "holdout_a"],
                         [e.name for e in context.exposures])

    def test_failed_refresh_clears_the_holdout_index(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp", [11])], [self.holdout_a()]))
        self.assertEqual([11], list(context._holdouts_by_id))
        context.set_data_failed(RuntimeError("boom"))
        self.assertEqual({}, context._holdouts_by_id)

    def test_refresh_swapping_the_covering_holdout_publishes_the_new_one(self):
        context = self.create_context(
            context_data([self.covered(1, "exp", [11])],
                         [self.holdout_a(), self.holdout_b()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        context.get_treatment("exp")
        self.refresh(context, context_data(
            [self.covered(1, "exp", [12])],
            [self.holdout_a(), self.holdout_b()]))
        context.get_treatment("exp")
        self.assertEqual(["exp", "holdout_a", "exp", "holdout_b"],
                         [e.name for e in context.exposures])


class SharedArmAcrossRefreshTest(HoldoutTestCase):

    def test_resolution_across_a_same_iteration_refresh_shares_its_arm(self):
        # The first experiment resolves holdout 11 from the old seeds while
        # a refresh installs new seeds for the same iteration; the second
        # experiment must reuse that arm instead of drawing a new one.
        old = context_data(
            [self.covered(1, "exp_a", [11]), self.covered(2, "exp_b", [11])],
            [holdout(11, "h", HOLDOUT_A_SEEDS)])
        new = context_data(
            [self.covered(1, "exp_a", [11]), self.covered(2, "exp_b", [11])],
            [holdout(11, "h", HOLDOUT_B_SEEDS)])
        context = self.create_context(old)
        original = context._get_resolution_state

        def refresh_after_read(name):
            state = original(name)
            context._get_resolution_state = original
            context.set_data(new)
            return state

        context._get_resolution_state = refresh_after_read
        self.assertEqual(0, context.get_treatment("exp_a"))
        self.assertEqual(0, context.get_treatment("exp_b"))
        self.assertEqual([("h", 0)],
                         [(e.name, e.variant) for e in context.exposures])

    def test_arm_survives_a_refresh_that_drops_and_restores_the_holdout(self):
        experiments = [self.covered(1, "exp_a", [11]),
                       self.covered(2, "exp_b", [11])]
        context = self.create_context(context_data(
            experiments, [holdout(11, "h", HOLDOUT_A_SEEDS)]))
        original = context._get_resolution_state

        def drop_after_read(name):
            state = original(name)
            context._get_resolution_state = original
            context.set_data(context_data(experiments, []))
            return state

        context._get_resolution_state = drop_after_read
        self.assertEqual(0, context.get_treatment("exp_a"))
        self.refresh(context, context_data(
            experiments, [holdout(11, "h", HOLDOUT_B_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_b"))
        self.assertEqual([("h", 0)],
                         [(e.name, e.variant) for e in context.exposures])


class QueueExposureHookTest(HoldoutTestCase):
    """A v0.2.4 Context subclass overriding queue_exposure still sees
    every exposure, covered experiments and holdouts included."""

    def test_subclass_override_sees_covered_and_holdout_exposures(self):
        from sdk.context import Context
        seen = []

        class Recording(Context):
            def queue_exposure(self, assignment):
                seen.append(assignment.name)
                return super().queue_exposure(assignment)

        context = self.create_context(
            context_data([self.covered(1, "exp_covered", [11]),
                          self.covered(2, "exp_held", [12]),
                          experiment(3, "exp_plain")],
                         [self.holdout_b(id=11, name="hb"),
                          self.holdout_a(id=12, name="ha")]),
            units={UNIT_TYPE: UID})
        context.__class__ = Recording
        for name in ("exp_covered", "exp_held", "exp_plain", "exp_covered"):
            context.get_treatment(name)
        self.assertEqual(["exp_covered", "hb", "ha", "exp_plain"], seen)
        self.assertEqual(["exp_covered", "hb", "ha", "exp_plain"],
                         [e.name for e in context.exposures])
