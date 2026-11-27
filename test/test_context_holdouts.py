"""Holdouts, ported from the Java SDK's ContextHoldoutTest (java-sdk main,
core-api/src/test/java/com/absmartly/sdk/ContextHoldoutTest.java) with the
JavaScript SDK (src/context.ts) as the reference where the two differ.

A holdout arrives in ContextData.holdouts; an experiment opts in with
holdoutIds. Arm 0 holds the unit out; in a 3-arm holdout arm 1 holds out
experiments that are not full-on. A held-out unit gets control values and
publishes no exposure for the covered experiment; each holdout publishes its
own ordinary exposure once per (holdout, unit type).
"""
import json
import unittest

from sdk.context_event_logger import EventType
from test.holdout_fixtures import (
    HOLDOUT_A_SEEDS, HOLDOUT_B_SEEDS, NORMAL_VARIANT, THREE_ARM_0_SEEDS,
    THREE_ARM_1_SEEDS, THREE_ARM_2_SEEDS, UID, UID_NOT_HELD_OUT, UNIT_TYPE,
    HoldoutFixture, context_data, experiment, holdout, three_arm_holdout,
    with_variables)

US_RULE = json.dumps({"rules": [{
    "name": "US Internal Users", "type": "assign",
    "conditions": {"and": [{"eq": [{"var": "country"}, {"value": "US"}]}]},
    "environments": [], "variant": 1}]})

AGE_AUDIENCE = json.dumps(
    {"filter": [{"gte": [{"var": "age"}, {"value": 20}]}]})


class HoldoutTestCase(HoldoutFixture, unittest.TestCase):
    def setUp(self):
        self.set_up_fixture()

    def covered(self, id, name, holdout_ids, **kwargs):
        return experiment(id, name, holdout_ids=holdout_ids, **kwargs)

    def holdout_a(self, id=11, name="holdout_a", **kwargs):
        return holdout(id, name, HOLDOUT_A_SEEDS, **kwargs)

    def holdout_b(self, id=12, name="holdout_b", **kwargs):
        return holdout(id, name, HOLDOUT_B_SEEDS, **kwargs)


class ContextHoldoutTest(HoldoutTestCase):

    def test_held_out_unit_gets_control_values_and_emits_no_exposure_for_covered_experiment(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_in", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.peek_treatment("exp_holdout_in"))
        context.get_treatment("exp_holdout_in")
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0))

    def test_not_held_out_unit_emits_holdout_exposure_variant_one_and_normal_exposure(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_holdout_out", [11])],
                         [self.holdout_a()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        self.assertEqual(0, context.get_treatment("exp_holdout_out"))
        self.assert_published(
            context, self.exposure(1, "exp_holdout_out", 0),
            self.holdout_exposure(11, "holdout_a", 1), uid=UID_NOT_HELD_OUT)

    def test_experiment_without_holdout_ids_emits_normally_even_for_held_out_unit(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_in", [11]),
             experiment(2, "exp_not_covered")], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_holdout_in"))
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_not_covered"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0),
            self.exposure(2, "exp_not_covered", NORMAL_VARIANT))

    def test_union_of_applicable_holdouts_suppresses_experiment_and_both_emit_own_exposure(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_multi_holdout", [11, 12])],
            [self.holdout_a(), self.holdout_b()]))
        self.assertEqual(0, context.get_treatment("exp_multi_holdout"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0),
            self.holdout_exposure(12, "holdout_b", 1))

    def test_union_rule_applies_when_the_higher_id_holdout_is_the_only_one_holding_unit_out(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_union_high_id_decides", [11, 12])],
            [holdout(11, "holdout_low_id", HOLDOUT_B_SEEDS),
             holdout(12, "holdout_high_id", HOLDOUT_A_SEEDS)]))
        self.assertEqual(0,
                         context.get_treatment("exp_union_high_id_decides"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_low_id", 1),
            self.holdout_exposure(12, "holdout_high_id", 0))

    def test_unit_not_held_out_by_either_holdout_is_not_suppressed(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_multi_holdout_miss", [11, 12])],
                         [self.holdout_a(), self.holdout_b()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        self.assertEqual(0, context.get_treatment("exp_multi_holdout_miss"))
        self.assert_published(
            context, self.exposure(1, "exp_multi_holdout_miss", 0),
            self.holdout_exposure(11, "holdout_a", 1),
            self.holdout_exposure(12, "holdout_b", 1), uid=UID_NOT_HELD_OUT)

    def test_holdout_suppresses_full_on_experiment_regardless_of_full_on_variant(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_fullon_holdout", [11], full_on_variant=2)],
            [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_fullon_holdout"))

    # --- Three-arm (all_full_on) holdouts

    def three_arm_context(self, arm_seeds, prefix):
        return self.create_context(context_data(
            [self.covered(1, prefix + "_non_fullon", [21]),
             self.covered(2, prefix + "_fullon", [21], full_on_variant=2)],
            [three_arm_holdout(21, "holdout_three_arm", arm_seeds)]))

    def test_three_arm_variant_zero_holds_out_both_full_on_and_non_full_on_experiments(self):
        context = self.three_arm_context(THREE_ARM_0_SEEDS, "exp_three_arm_0")
        self.assertEqual(0, context.get_treatment("exp_three_arm_0_non_fullon"))
        self.assertEqual(0, context.get_treatment("exp_three_arm_0_fullon"))
        self.assert_published(
            context, self.holdout_exposure(21, "holdout_three_arm", 0))

    def test_three_arm_variant_one_forces_non_full_on_experiment_to_control_but_assigns_full_on_experiment_normally(self):
        context = self.three_arm_context(THREE_ARM_1_SEEDS, "exp_three_arm_1")
        self.assertEqual(0, context.get_treatment("exp_three_arm_1_non_fullon"))
        self.assertEqual(2, context.get_treatment("exp_three_arm_1_fullon"))
        self.assert_published(
            context, self.holdout_exposure(21, "holdout_three_arm", 1),
            self.exposure(2, "exp_three_arm_1_fullon", 2, full_on=True))

    def test_three_arm_variant_two_evaluates_both_experiment_kinds_normally(self):
        context = self.three_arm_context(THREE_ARM_2_SEEDS, "exp_three_arm_2")
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_three_arm_2_non_fullon"))
        self.assertEqual(2, context.get_treatment("exp_three_arm_2_fullon"))
        self.assert_published(
            context,
            self.exposure(1, "exp_three_arm_2_non_fullon", NORMAL_VARIANT),
            self.holdout_exposure(21, "holdout_three_arm", 2),
            self.exposure(2, "exp_three_arm_2_fullon", 2, full_on=True))

    def test_two_arm_holdout_wins_union_even_when_three_arm_would_not_hold_out(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_union_two_arm_wins", [11, 22])],
            [holdout(11, "holdout_two_arm", HOLDOUT_A_SEEDS),
             three_arm_holdout(22, "holdout_three_arm", THREE_ARM_2_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_union_two_arm_wins"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_two_arm", 0),
            self.holdout_exposure(22, "holdout_three_arm", 2))

    def test_three_arm_holdout_wins_union_even_when_two_arm_would_not_hold_out(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_union_three_arm_wins", [11, 22])],
            [holdout(11, "holdout_two_arm", HOLDOUT_B_SEEDS),
             three_arm_holdout(22, "holdout_three_arm", THREE_ARM_1_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_union_three_arm_wins"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_two_arm", 1),
            self.holdout_exposure(22, "holdout_three_arm", 1))

    def test_three_arm_arm_one_defers_to_normal_path_so_audience_mismatch_still_wins_for_full_on_experiment(self):
        for seeds, arm in ((THREE_ARM_1_SEEDS, 1), (THREE_ARM_2_SEEDS, 2)):
            with self.subTest(arm=arm):
                name = f"exp_three_arm_{arm}_audience_fullon"
                context = self.create_context(context_data(
                    [self.covered(1, name, [21], full_on_variant=2,
                                  audienceStrict=True,
                                  audience=AGE_AUDIENCE)],
                    [three_arm_holdout(21, "holdout_three_arm", seeds)]))
                context.set_attribute("age", 5)
                self.assertEqual(0, context.get_treatment(name))
                event = self.assert_published(
                    context,
                    self.exposure(1, name, 0, assigned=False,
                                  audience_mismatch=True),
                    self.holdout_exposure(21, "holdout_three_arm", arm))
                self.assertEqual([("age", 5)],
                                 [(a.name, a.value) for a in event.attributes])

    def test_unconfigured_unit_type_gets_control_values_and_emits_no_exposure_at_all(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_user_holdout", [11], unit_type="user_id")],
            [holdout(11, "holdout_user", HOLDOUT_A_SEEDS,
                     unit_type="user_id")]))
        self.assertEqual(0, context.peek_treatment("exp_user_holdout"))
        context.get_treatment("exp_user_holdout")
        # The holdout cannot be evaluated without the unit, so it neither
        # suppresses nor publishes; the experiment publishes its unassigned
        # exposure, as in the JS SDK.
        event = self.publish(context)
        self.assertEqual(
            [self.exposure(1, "exp_user_holdout", 0, unit="user_id",
                           assigned=False)],
            self.exposure_tuples(event.exposures))
        self.assertEqual(0, context.get_pending_count())

    def test_assigns_normally_when_holdouts_key_is_absent(self):
        context = self.create_context(context_data(
            [experiment(1, "exp_no_holdouts_key")]))
        self.assertEqual(NORMAL_VARIANT,
                         context.peek_treatment("exp_no_holdouts_key"))

    def test_holdout_id_absent_from_holdouts_array_is_ignored_and_experiment_assigns_normally(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_dangling_holdout_id", [999])]))
        self.assertEqual(NORMAL_VARIANT,
                         context.peek_treatment("exp_dangling_holdout_id"))

    def test_custom_assignment_cannot_override_held_out_variant(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_holdout_custom", [11])],
                         [self.holdout_a()]),
            custom_assignments={"exp_holdout_custom": 3})
        self.assertEqual(0, context.peek_treatment("exp_holdout_custom"))

    def test_reuses_cached_held_out_assignment_with_custom_assignment(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_holdout_custom_cache", [11])],
                         [self.holdout_a()]),
            custom_assignments={"exp_holdout_custom_cache": 3})
        first = context.get_assignment("exp_holdout_custom_cache")
        self.assertEqual(0, context.get_treatment("exp_holdout_custom_cache"))
        self.assertEqual(0, context.get_treatment("exp_holdout_custom_cache"))
        self.assertIs(first, context.get_assignment("exp_holdout_custom_cache"))
        self.assertEqual(1, context.get_pending_count())

    def test_override_takes_precedence_over_holdout(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_holdout_override", [11])],
                         [self.holdout_a()]),
            overrides={"exp_holdout_override": 3})
        self.assertEqual(3, context.peek_treatment("exp_holdout_override"))

    def test_get_treatment_on_overridden_experiment_triggers_applicable_holdout_exposure_both_arms(self):
        for uid, arm in ((UID, 0), (UID_NOT_HELD_OUT, 1)):
            with self.subTest(arm=arm):
                context = self.create_context(
                    context_data([self.covered(1, "exp_override", [11])],
                                 [self.holdout_a()]),
                    units={UNIT_TYPE: uid}, overrides={"exp_override": 3})
                self.assertEqual(3, context.get_treatment("exp_override"))
                self.assert_published(
                    context,
                    self.exposure(1, "exp_override", 3, assigned=False,
                                  overridden=True),
                    self.holdout_exposure(11, "holdout_a", arm), uid=uid)

    def test_holdout_takes_precedence_over_audience_mismatch(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_audience", [11],
                          audienceStrict=True, audience=AGE_AUDIENCE)],
            [self.holdout_a()]))
        context.set_attribute("age", 5)
        self.assertEqual(0, context.peek_treatment("exp_holdout_audience"))
        context.get_treatment("exp_holdout_audience")
        # JS skips the audience of a held-out experiment entirely.
        self.assertFalse(
            context.get_assignment("exp_holdout_audience").audience_mismatch)

    def test_holdout_exposure_emitted_once_per_context_not_per_suppressed_experiment(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_shared_a", [11]),
             self.covered(2, "exp_shared_b", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_shared_a"))
        self.assertEqual(0, context.get_treatment("exp_shared_b"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0))

    def test_holdout_exposure_fires_once_even_when_triggering_experiment_is_not_suppressed(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_shared_a", [11]),
                          self.covered(2, "exp_shared_b", [11])],
                         [self.holdout_a()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        context.get_treatment("exp_shared_a")
        context.get_treatment("exp_shared_b")
        self.assert_published(
            context, self.exposure(1, "exp_shared_a", 0),
            self.holdout_exposure(11, "holdout_a", 1),
            self.exposure(2, "exp_shared_b", 0), uid=UID_NOT_HELD_OUT)

    def test_reuses_cached_suppressed_assignment_across_repeated_calls(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_cache", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_holdout_cache"))
        self.assertEqual(0, context.get_treatment("exp_holdout_cache"))
        self.assertEqual(1, context.get_pending_count())

    # --- Refresh

    def test_refresh_with_seed_change_same_iteration_keeps_unit_in_original_arm_and_does_not_re_expose(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_seed", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_seed"))
        self.assertEqual(1, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_seed", [11])],
            [holdout(11, "holdout_a", HOLDOUT_B_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_seed"))
        self.assertEqual(1, context.get_pending_count())

    def test_refresh_with_cosmetic_holdout_edit_does_not_re_expose_held_out_unit(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_cosmetic", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_cosmetic"))
        self.assertEqual(1, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_cosmetic", [11])],
            [holdout(11, "holdout_a_renamed", HOLDOUT_A_SEEDS,
                     applications=[{"name": "website"}],
                     variants=[{"name": "Control", "config": None},
                               {"name": "HeldOut", "config": None}])]))
        self.assertEqual(0, context.get_treatment("exp_cosmetic"))
        self.assertEqual(1, context.get_pending_count())

    def test_refresh_with_cosmetic_holdout_edit_does_not_duplicate_covered_experiment_exposure(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_cosmetic_covered", [11])],
                         [self.holdout_a()]),
            units={UNIT_TYPE: UID_NOT_HELD_OUT})
        self.assertEqual(0, context.get_treatment("exp_cosmetic_covered"))
        self.assertEqual(2, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_cosmetic_covered", [11])],
            [holdout(11, "holdout_a_renamed", HOLDOUT_A_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_cosmetic_covered"))
        self.assertEqual(2, context.get_pending_count())

    def test_refresh_with_iteration_bump_reassigns_to_exactly_one_new_arm(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_iteration", [11])],
            [holdout(11, "holdout_a", HOLDOUT_B_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_iteration"))
        self.assertEqual(2, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_iteration", [11])],
            [holdout(11, "holdout_a", HOLDOUT_A_SEEDS, iteration=2)]))
        self.assertEqual(0, context.get_treatment("exp_iteration"))
        self.assertEqual(3, context.get_pending_count())
        self.assertEqual(0, context.get_treatment("exp_iteration"))
        self.assertEqual(3, context.get_pending_count())

    def test_refreshed_seed_does_not_desync_suppression_from_pinned_holdout_arm_for_newly_evaluated_experiment(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_desync_a", [11])], [self.holdout_a()]))
        self.assertEqual(0, context.get_treatment("exp_desync_a"))
        self.refresh(context, context_data(
            [self.covered(1, "exp_desync_a", [11]),
             self.covered(2, "exp_desync_b", [11])],
            [holdout(11, "holdout_a", HOLDOUT_B_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_desync_b"))
        self.assertEqual(0, context.get_treatment("exp_desync_a"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0))

    # --- Arm count pinned with the arm across a same-iteration arity change

    def test_refresh_from_two_arm_to_three_arm_same_iteration_does_not_reinterpret_deferring_arm_as_full_on_only(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_arity_a", [31])],
            [holdout(31, "holdout_arity", HOLDOUT_B_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_arity_a"))
        self.refresh(context, context_data(
            [self.covered(1, "exp_arity_a", [31]),
             self.covered(2, "exp_arity_b", [31])],
            [three_arm_holdout(31, "holdout_arity", THREE_ARM_1_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_arity_b"))
        self.assert_published(
            context, self.exposure(1, "exp_arity_a", NORMAL_VARIANT),
            self.holdout_exposure(31, "holdout_arity", 1),
            self.exposure(2, "exp_arity_b", NORMAL_VARIANT))

    def test_refresh_from_three_arm_to_two_arm_same_iteration_keeps_full_on_only_arm_suppressing_non_full_on_experiment(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_arity_rev_a", [41])],
            [three_arm_holdout(41, "holdout_arity_rev", THREE_ARM_1_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_arity_rev_a"))
        self.assertEqual(1, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_arity_rev_a", [41]),
             self.covered(2, "exp_arity_rev_b", [41])],
            [holdout(41, "holdout_arity_rev", HOLDOUT_B_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_arity_rev_b"))
        self.assert_published(
            context, self.holdout_exposure(41, "holdout_arity_rev", 1))

    def test_experiments_evaluated_before_and_after_same_iteration_arity_change_agree_on_suppression(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_pre", [71])],
            [holdout(71, "holdout_consistency", HOLDOUT_B_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_pre"))
        self.refresh(context, context_data(
            [self.covered(1, "exp_pre", [71]),
             self.covered(2, "exp_post", [71])],
            [three_arm_holdout(71, "holdout_consistency",
                               THREE_ARM_1_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_post"))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_pre"))

    def test_trigger_fires_holdout_exposure_from_decision_epoch_despite_refresh_racing_between_decision_and_trigger(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_epoch_race", [11])],
            [holdout(11, "holdout_h", HOLDOUT_B_SEEDS)]))
        self.client.refresh_data = context_data(
            [self.covered(1, "exp_epoch_race", [11])],
            [holdout(11, "holdout_h", HOLDOUT_A_SEEDS, iteration=2)])

        def refresh_on_own_exposure(event_type, data):
            if event_type == EventType.EXPOSURE and data.id == 1:
                context.refresh()

        self.logger.on_event = refresh_on_own_exposure
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_epoch_race"))
        self.logger.on_event = None
        self.assert_published(
            context, self.exposure(1, "exp_epoch_race", NORMAL_VARIANT),
            self.holdout_exposure(11, "holdout_h", 1))

    # --- A unit set after the assignment was resolved (scenario 221)

    def late_unit_context(self, seeds, name="exp_late", full_on_variant=2,
                          holdout_ids=(11,), holdouts=None, **kwargs):
        return self.create_context(context_data(
            [self.covered(1, name, list(holdout_ids), unit_type="user_id",
                          full_on_variant=full_on_variant)],
            holdouts or [holdout(11, "holdout_user_id", seeds,
                                 unit_type="user_id")]),
            units={}, **kwargs)

    def test_set_unit_invalidates_null_holdout_snapshot_so_the_holdout_exposure_is_not_lost_forever(self):
        context = self.late_unit_context(HOLDOUT_B_SEEDS)
        self.assertEqual(2, context.peek_treatment("exp_late"))
        context.set_unit("user_id", UID)
        self.assertEqual(2, context.get_treatment("exp_late"))
        self.assertEqual(2, context.get_pending_count())
        self.assert_published(
            context, self.exposure(1, "exp_late", 2, unit="user_id",
                                   full_on=True),
            self.holdout_exposure(11, "holdout_user_id", 1, unit="user_id"),
            unit="user_id")

    def test_set_unit_does_not_evict_already_exposed_assignment_so_no_duplicate_exposure(self):
        context = self.late_unit_context(HOLDOUT_B_SEEDS)
        self.assertEqual(2, context.get_treatment("exp_late"))
        self.assertEqual(1, context.get_pending_count())
        exposed = context.get_assignment("exp_late")
        context.set_unit("user_id", UID)
        self.assertEqual(2, context.get_treatment("exp_late"))
        self.assertEqual(1, context.get_pending_count())
        self.assertIs(exposed, context.get_assignment("exp_late"))

    def test_set_unit_for_unrelated_unit_type_does_not_evict_exposed_assignment(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_unrelated_unit", [11])],
            [holdout(11, "holdout_a", HOLDOUT_B_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_unrelated_unit"))
        self.assertEqual(2, context.get_pending_count())
        context.set_unit("other_unit_type", "some-other-uid")
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_unrelated_unit"))
        self.assertEqual(2, context.get_pending_count())

    def test_set_unit_evicts_only_the_affected_entry_and_leaves_the_other_untouched(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_late_unit", [11], unit_type="user_id",
                          full_on_variant=2),
             self.covered(2, "exp_present_unit", [12])],
            [holdout(11, "holdout_late", HOLDOUT_B_SEEDS, unit_type="user_id"),
             holdout(12, "holdout_present", HOLDOUT_B_SEEDS)]))
        self.assertEqual(2, context.peek_treatment("exp_late_unit"))
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_present_unit"))
        self.assertEqual(2, context.get_pending_count())
        context.set_unit("user_id", UID)
        self.assertEqual(2, context.get_treatment("exp_late_unit"))
        self.assertEqual(4, context.get_pending_count())
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_present_unit"))
        self.assertEqual(4, context.get_pending_count())

    def test_set_unit_evicts_using_the_covered_experiments_unit_type_not_the_holdouts_declared_unit_type(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_mismatched", [11], unit_type="A",
                          full_on_variant=2)],
            [holdout(11, "holdout_declares_b", HOLDOUT_B_SEEDS,
                     unit_type="B")]), units={})
        self.assertEqual(2, context.peek_treatment("exp_mismatched"))
        context.set_unit("A", UID)
        self.assertEqual(2, context.get_treatment("exp_mismatched"))
        self.assertEqual(2, context.get_pending_count())

    def test_set_unit_recomputes_suppression_coherently_when_late_resolved_holdout_suppresses(self):
        context = self.late_unit_context(HOLDOUT_A_SEEDS)
        self.assertEqual(2, context.peek_treatment("exp_late"))
        context.set_unit("user_id", UID)
        self.assertEqual(0, context.get_treatment("exp_late"))
        self.assertEqual(1, context.get_pending_count())
        self.assert_published(
            context,
            self.holdout_exposure(11, "holdout_user_id", 0, unit="user_id"),
            unit="user_id")

    # Java's detached-assignment cases: a caller holding an assignment that
    # set_unit evicted (here a concurrent thread; Java uses reflection) must
    # not expose it next to the replacement.

    def test_detached_treatment_assignment_cannot_publish_beside_suppressing_replacement(self):
        context = self.late_unit_context(HOLDOUT_A_SEEDS)
        retained = context.get_assignment("exp_late")
        context.set_unit("user_id", UID)
        self.assertEqual(0, context.get_treatment("exp_late"))
        self.assertEqual(1, context.get_pending_count())
        self.assertFalse(context._expose(retained))
        self.assertEqual(1, context.get_pending_count())
        self.assert_published(
            context,
            self.holdout_exposure(11, "holdout_user_id", 0, unit="user_id"),
            unit="user_id")

    def test_detached_treatment_assignment_retries_current_entry_without_losing_exposure(self):
        context = self.late_unit_context(HOLDOUT_B_SEEDS)
        retained = context.get_assignment("exp_late")
        resolved = []
        original = context.get_assignment

        def get_assignment(name, exposed_at=None):
            # The first resolution returns the assignment set_unit retires
            # before it is exposed, as a racing thread would see it.
            if not resolved:
                resolved.append(name)
                context.set_unit("user_id", UID)
                return retained
            return original(name, exposed_at=exposed_at)

        context.get_assignment = get_assignment
        self.assertEqual(2, context.get_treatment("exp_late"))
        context.get_assignment = original
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual(2, context.get_treatment("exp_late"))
        self.assertEqual(2, context.get_pending_count())
        self.assert_published(
            context, self.exposure(1, "exp_late", 2, unit="user_id",
                                   full_on=True),
            self.holdout_exposure(11, "holdout_user_id", 1, unit="user_id"),
            unit="user_id")

    def test_detached_treatment_returns_the_replacement_variant(self):
        context = self.late_unit_context(HOLDOUT_A_SEEDS)
        retained = context.get_assignment("exp_late")
        calls = []
        original = context.get_assignment

        def get_assignment(name, exposed_at=None):
            if not calls:
                calls.append(name)
                context.set_unit("user_id", UID)
                return retained
            return original(name, exposed_at=exposed_at)

        context.get_assignment = get_assignment
        self.assertEqual(0, context.get_treatment("exp_late"))
        self.assertEqual(1, context.get_pending_count())

    def test_treatment_exposure_settles_after_two_consecutive_retirements(self):
        context = self.create_context(context_data(
            [experiment(1, "exp_settled", full_on_variant=1)]))
        stale = []
        original = context.get_assignment

        def get_assignment(name, exposed_at=None):
            assignment = original(name, exposed_at=exposed_at)
            if len(stale) < 2:
                stale.append(assignment)
                context._retire(assignment)
                del context.assignment_cache[name]
            return assignment

        context.get_assignment = get_assignment
        self.assertEqual(1, context.get_treatment("exp_settled"))
        self.assertEqual(1, context.get_pending_count())
        self.assertTrue(all(not a.exposed.value for a in stale))

    def test_exposure_settlement_stops_after_the_bounded_number_of_retirements(self):
        context = self.create_context(context_data(
            [experiment(1, "exp_bounded_retry", full_on_variant=1)]))
        retired = context.get_assignment("exp_bounded_retry")
        context._retire(retired)
        resolutions = []

        def get_assignment(name, exposed_at=None):
            resolutions.append(name)
            return retired

        context.get_assignment = get_assignment
        self.assertEqual(1, context.get_treatment("exp_bounded_retry"))
        self.assertEqual(3, len(resolutions))
        self.assertEqual(0, context.get_pending_count())

    def test_detached_variable_assignment_reresolves_the_key_to_a_new_winning_experiment(self):
        original_exp = self.covered(2, "exp_old", [11], unit_type="user_id",
                                    full_on_variant=1)
        original_exp["variants"][1]["config"] = '{"detached_var":"old"}'
        hold = holdout(11, "holdout_detached_variable", HOLDOUT_B_SEEDS,
                       unit_type="user_id")
        context = self.create_context(
            context_data([original_exp], [hold]), units={})
        retained = context.get_assignment("exp_old")
        winner = self.covered(1, "exp_winner", [11], unit_type="user_id",
                              full_on_variant=1)
        winner["variants"][1]["config"] = '{"detached_var":"new winner"}'
        calls = []
        original = context.get_assignment

        def get_assignment(name, exposed_at=None):
            # The first lookup sees the pre-refresh index and a retained
            # assignment that set_unit retires before it is exposed.
            if not calls:
                calls.append(name)
                context.set_unit("user_id", UID)
                self.refresh(context, context_data([winner, original_exp],
                                                   [hold]))
                return retained
            return original(name, exposed_at=exposed_at)

        context.get_assignment = get_assignment
        self.assertEqual("new winner",
                         context.get_variable_value("detached_var", "default"))
        context.get_assignment = original
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual("new winner",
                         context.get_variable_value("detached_var", "default"))
        self.assertEqual(2, context.get_pending_count())
        self.assert_published(
            context,
            self.holdout_exposure(11, "holdout_detached_variable", 1,
                                  unit="user_id"),
            self.exposure(1, "exp_winner", 1, unit="user_id", full_on=True),
            unit="user_id")

    def test_trigger_applicable_holdout_exposures_never_live_resolves_a_pinned_null_entry_for_an_already_exposed_assignment(self):
        exp = self.covered(1, "exp_pinned_null", [11], unit_type="user_id",
                           full_on_variant=1)
        exp["variants"][1]["config"] = '{"my_var":"value_from_variant"}'
        context = self.create_context(context_data(
            [exp], [holdout(11, "holdout_pinned_null", HOLDOUT_A_SEEDS,
                            unit_type="user_id")]), units={})
        self.assertEqual(1, context.get_treatment("exp_pinned_null"))
        self.assertEqual(1, context.get_pending_count())
        context.set_unit("user_id", UID)
        self.assertEqual("value_from_variant",
                         context.get_variable_value("my_var", "default"))
        self.assertEqual(1, context.get_pending_count())

    def test_set_unit_evicts_assignment_with_multiple_holdouts_declaring_different_unit_types(self):
        context = self.late_unit_context(
            None, name="exp_multi_unit_types", holdout_ids=(11, 12, 13),
            holdouts=[holdout(11, "holdout_11", HOLDOUT_B_SEEDS,
                              unit_type="type_x"),
                      holdout(12, "holdout_12", HOLDOUT_B_SEEDS,
                              unit_type="type_y"),
                      holdout(13, "holdout_13", HOLDOUT_B_SEEDS,
                              unit_type="user_id")])
        self.assertEqual(2, context.peek_treatment("exp_multi_unit_types"))
        context.set_unit("user_id", UID)
        self.assertEqual(2, context.get_treatment("exp_multi_unit_types"))
        self.assertEqual(4, context.get_pending_count())

    def test_one_holdout_covering_two_unit_types_keeps_independent_exposure_state_per_unit_type(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_unit_a1", [11], unit_type="user_id"),
             self.covered(2, "exp_unit_b", [11], unit_type="session_id"),
             self.covered(3, "exp_unit_a2", [11], unit_type="user_id")],
            [holdout(11, "holdout_shared", HOLDOUT_B_SEEDS,
                     unit_type="user_id")]),
            units={"user_id": UID, "session_id": UID})
        for name in ("exp_unit_a1", "exp_unit_b", "exp_unit_a2"):
            self.assertEqual(NORMAL_VARIANT, context.get_treatment(name))
        self.assertEqual(5, context.get_pending_count())
        event = self.publish(context)
        self.assertEqual([("user_id", 1), ("session_id", 1)],
                         [(e.unit, e.variant) for e in event.exposures
                          if e.id == 11])

    def test_set_unit_with_no_cached_assignment_does_not_throw_and_subsequent_assignment_is_normal(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_no_prior", [11])],
            [holdout(11, "holdout_a", HOLDOUT_B_SEEDS)]), units={})
        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_no_prior"))

    def test_set_unit_called_twice_with_same_uid_is_a_no_op_and_does_not_throw(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_twice", [11])],
            [holdout(11, "holdout_a", HOLDOUT_B_SEEDS)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_twice"))
        self.assertEqual(2, context.get_pending_count())
        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_twice"))
        self.assertEqual(2, context.get_pending_count())

    def test_set_unit_redundant_call_does_not_evict_fully_resolved_unexposed_holdout_snapshot(self):
        hold = holdout(11, "holdout_a", HOLDOUT_B_SEEDS)
        context = self.create_context(context_data(
            [self.covered(1, "exp_redundant", [11])], [hold]))
        self.assertEqual(NORMAL_VARIANT, context.peek_treatment("exp_redundant"))
        self.assertEqual(0, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_redundant", [11], split=[1.0, 0.0])],
            [hold]))
        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_redundant"))
        self.assert_published(
            context, self.exposure(1, "exp_redundant", NORMAL_VARIANT),
            self.holdout_exposure(11, "holdout_a", 1))

    def test_peek_variable_value_then_set_unit_then_get_variable_value_recomputes_under_late_suppressing_holdout(self):
        exp = self.covered(1, "exp_var_late", [11], unit_type="user_id",
                           full_on_variant=1)
        exp["variants"][1]["config"] = '{"my_var":"value_from_variant"}'
        context = self.create_context(context_data(
            [exp], [holdout(11, "holdout_var_late", HOLDOUT_A_SEEDS,
                            unit_type="user_id")]), units={})
        self.assertEqual("value_from_variant",
                         context.peek_variable_value("my_var", "default"))
        self.assertEqual(0, context.get_pending_count())
        context.set_unit("user_id", UID)
        self.assertEqual("default",
                         context.get_variable_value("my_var", "default"))
        self.assert_published(
            context,
            self.holdout_exposure(11, "holdout_var_late", 0, unit="user_id"),
            unit="user_id")

    def test_set_unit_does_not_evict_override_assignment_and_holdout_resolves_at_exposure_time(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_override_late", [11],
                                       unit_type="user_id")],
                         [holdout(11, "holdout_override_late",
                                  HOLDOUT_B_SEEDS, unit_type="user_id")]),
            units={}, overrides={"exp_override_late": 3})
        self.assertEqual(3, context.peek_treatment("exp_override_late"))
        context.set_unit("user_id", UID)
        self.assertEqual(3, context.get_treatment("exp_override_late"))
        self.assertEqual(2, context.get_pending_count())
        self.assert_published(
            context,
            self.exposure(1, "exp_override_late", 3, unit="user_id",
                          assigned=False, overridden=True),
            self.holdout_exposure(11, "holdout_override_late", 1,
                                  unit="user_id"),
            unit="user_id")

    def test_set_unit_evicts_null_snapshot_for_custom_assignment_and_custom_applies_after_recompute(self):
        context = self.create_context(
            context_data([self.covered(1, "exp_custom_late", [11],
                                       unit_type="user_id")],
                         [holdout(11, "holdout_custom_late", HOLDOUT_B_SEEDS,
                                  unit_type="user_id")]),
            units={}, custom_assignments={"exp_custom_late": 3})
        self.assertEqual(0, context.peek_treatment("exp_custom_late"))
        context.set_unit("user_id", UID)
        self.assertEqual(3, context.get_treatment("exp_custom_late"))
        self.assert_published(
            context,
            self.exposure(1, "exp_custom_late", 3, unit="user_id",
                          custom=True),
            self.holdout_exposure(11, "holdout_custom_late", 1,
                                  unit="user_id"),
            unit="user_id")

    # --- Verdict vectors (collector test_holdouts.py
    # TestCollectorHoldoutVerdictVectors, pinned by the Java SDK)

    def verdict_context(self, uid, *holdouts):
        return self.create_context(
            context_data([self.covered(9, "verdict_vectors_experiment",
                                       [h["id"] for h in holdouts],
                                       unit_type="verdict_unit_type")],
                         list(holdouts)),
            units={"verdict_unit_type": uid})

    @staticmethod
    def verdict_holdout(id, seed_hi, seed_lo, split):
        return holdout(id, f"holdout_{id}", (seed_hi, seed_lo),
                       unit_type="verdict_unit_type", split=split)

    def assert_held_out_by(self, context, holdout_id, uid):
        self.assertEqual(0, context.get_treatment("verdict_vectors_experiment"))
        self.assert_published(
            context, self.holdout_exposure(holdout_id, f"holdout_{holdout_id}",
                                           0, unit="verdict_unit_type"),
            unit="verdict_unit_type", uid=uid)

    def assert_not_held_out(self, context, holdout_id):
        context.get_treatment("verdict_vectors_experiment")
        event = self.publish(context)
        self.assertIn((holdout_id, f"holdout_{holdout_id}", 1),
                      [(e.id, e.name, e.variant) for e in event.exposures])

    def test_unicode_unit_ids(self):
        self.assert_held_out_by(self.verdict_context(
            "façade", self.verdict_holdout(107, 0, 42, [0.1, 0.9])),
            107, "façade")
        self.assert_not_held_out(self.verdict_context(
            "unicode_emoji_\U0001F680_0",
            self.verdict_holdout(107, 0, 42, [0.1, 0.9])), 107)

    def test_signed_seed_halves(self):
        seed = -9223372034707292160
        seed_hi = (seed >> 32)
        seed_lo = ((seed & 0xffffffff) ^ 0x80000000) - 0x80000000
        self.assertEqual((-2147483648, -2147483648), (seed_hi, seed_lo))
        self.assert_held_out_by(self.verdict_context(
            "signed_unit_4",
            self.verdict_holdout(106, seed_hi, seed_lo, [0.1, 0.9])),
            106, "signed_unit_4")
        self.assert_not_held_out(self.verdict_context(
            "signed_unit_b_1",
            self.verdict_holdout(106, seed_hi, seed_lo, [0.1, 0.9])), 106)

    def test_percentage_boundary_at_one_percent(self):
        self.assert_held_out_by(self.verdict_context(
            "pct1_unit_188",
            self.verdict_holdout(105, 0, 999999, [0.01, 0.99])),
            105, "pct1_unit_188")
        self.assert_not_held_out(self.verdict_context(
            "pct1_unit_0",
            self.verdict_holdout(105, 0, 999999, [0.01, 0.99])), 105)

    def test_assignment_probability_boundary_around_ten_percent(self):
        self.assert_held_out_by(self.verdict_context(
            "boundary_unit_175653",
            self.verdict_holdout(107, 0, 42, [0.1, 0.9])),
            107, "boundary_unit_175653")
        self.assert_not_held_out(self.verdict_context(
            "boundary_unit_75792",
            self.verdict_holdout(107, 0, 42, [0.1, 0.9])), 107)

    def test_unit_held_out_by_two_holdouts_simultaneously(self):
        context = self.verdict_context(
            "dual_holdout_unit_5",
            self.verdict_holdout(107, 0, 42, [0.1, 0.9]),
            self.verdict_holdout(108, 0, 55, [0.1, 0.9]))
        self.assertEqual(0, context.get_treatment("verdict_vectors_experiment"))
        self.assert_published(
            context,
            self.holdout_exposure(107, "holdout_107", 0,
                                  unit="verdict_unit_type"),
            self.holdout_exposure(108, "holdout_108", 0,
                                  unit="verdict_unit_type"),
            unit="verdict_unit_type", uid="dual_holdout_unit_5")

    # --- Variables

    def test_variable_lookup_fires_holdout_exposure_for_both_held_out_and_non_held_out_units(self):
        for uid, pending in ((UID, 1), (UID_NOT_HELD_OUT, 2)):
            with self.subTest(uid=uid):
                exp = self.covered(1, "exp_var", [11])
                exp["variants"][1]["config"] = '{"var_a":"value_a"}'
                context = self.create_context(
                    context_data([exp], [self.holdout_a()]),
                    units={UNIT_TYPE: uid})
                self.assertEqual("default",
                                 context.get_variable_value("var_a", "default"))
                self.assertEqual(pending, context.get_pending_count())

    def test_variable_key_resolution_skips_suppressed_assignment_in_favor_of_assigned_one(self):
        suppressed = self.covered(1, "exp_var_key_suppressed", [11])
        suppressed["variants"][1]["config"] = '{"shared":"from_suppressed"}'
        assigned = experiment(2, "exp_var_key_assigned")
        assigned["variants"][1]["config"] = '{"shared":"from_assigned"}'
        context = self.create_context(context_data(
            [suppressed, assigned], [self.holdout_a()]))
        self.assertEqual("from_assigned",
                         context.get_variable_value("shared", "default"))
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_a", 0),
            self.exposure(2, "exp_var_key_assigned", NORMAL_VARIANT))

    def test_peek_variable_value_never_triggers_holdout_exposure_for_evaluated_candidates(self):
        suppressed = self.covered(1, "exp_peek_suppressed", [11])
        suppressed["variants"][1]["config"] = '{"shared_peek":"from_suppressed"}'
        assigned = experiment(2, "exp_peek_assigned")
        assigned["variants"][1]["config"] = '{"shared_peek":"from_assigned"}'
        context = self.create_context(context_data(
            [suppressed, assigned], [self.holdout_a()]))
        self.assertEqual("from_assigned",
                         context.peek_variable_value("shared_peek", "default"))
        self.assertEqual(0, context.get_pending_count())

    # --- A throwing event logger

    def throwing_logger(self, predicate):
        def handler(event_type, data):
            if event_type == EventType.EXPOSURE and predicate(data):
                raise RuntimeError("boom")
        self.logger.on_event = handler

    def test_throwing_logger_does_not_permanently_lose_sibling_holdout_exposure(self):
        self.throwing_logger(lambda e: e.id == 11)
        context = self.create_context(context_data(
            [self.covered(1, "exp_throwing", [11, 12])],
            [self.holdout_a(), self.holdout_b()]))
        # The SDK contains logger errors (it never raises them to the caller,
        # unlike Java); both holdout exposures are still queued.
        with self.assertLogs("sdk.context", "ERROR"):
            self.assertEqual(0, context.get_treatment("exp_throwing"))
        self.assertEqual(2, context.get_pending_count())

    def test_throwing_logger_does_not_make_experiment_or_holdout_exposure_retryable(self):
        self.throwing_logger(lambda e: e.id == 1)
        context = self.create_context(context_data(
            [self.covered(1, "exp_terminal", [11])],
            [holdout(11, "holdout_terminal", HOLDOUT_B_SEEDS)]))
        with self.assertLogs("sdk.context", "ERROR"):
            context.get_treatment("exp_terminal")
        self.logger.on_event = None
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_terminal"))
        self.assert_published(
            context, self.exposure(1, "exp_terminal", NORMAL_VARIANT),
            self.holdout_exposure(11, "holdout_terminal", 1))

    def test_throwing_logger_on_suppressed_experiments_only_holdout_still_schedules_flush(self):
        self.throwing_logger(lambda e: True)
        context = self.create_context(
            context_data([self.covered(1, "exp_stranded", [11])],
                         [self.holdout_a()]), publish_delay=0.01)
        with self.assertLogs("sdk.context", "ERROR"):
            context.get_treatment("exp_stranded")
        self.client.wait_for_publish(1)
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(
            [self.holdout_exposure(11, "holdout_a", 0)],
            self.exposure_tuples(self.client.published[0].exposures))

    # --- Malformed holdouts

    def assert_assigns_normally(self, holdouts, holdout_ids=(11,)):
        context = self.create_context(context_data(
            [self.covered(1, "exp_malformed", list(holdout_ids))], holdouts))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_malformed"))
        self.assert_published(
            context, self.exposure(1, "exp_malformed", NORMAL_VARIANT))

    def test_null_holdout_array_element_is_ignored_and_experiment_assigns_normally(self):
        self.assert_assigns_normally([None])

    def test_holdout_with_null_split_is_ignored_and_experiment_assigns_normally(self):
        self.assert_assigns_normally([self.holdout_a(split=None) | {"split": None}])

    def test_holdout_with_empty_split_is_ignored_and_experiment_assigns_normally(self):
        self.assert_assigns_normally([self.holdout_a(split=[]) | {"split": []}])

    # --- Cache and publish invariants

    def test_stale_holdout_reference_never_overwrites_newer_pinned_cache_entry(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_f", [11])],
            [holdout(11, "holdout_h", HOLDOUT_A_SEEDS)]))
        self.assertEqual(0, context.get_treatment("exp_f"))
        stale = context.get_assignment("exp_f").holdouts[0]
        self.refresh(context, context_data(
            [self.covered(1, "exp_f", [11]), self.covered(2, "exp_g", [11])],
            [holdout(11, "holdout_h", HOLDOUT_B_SEEDS, iteration=2)]))
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_g"))
        self.assertEqual(3, context.get_pending_count())
        live = context._get_holdout_assignment(stale, UNIT_TYPE)
        self.assertEqual((2, 1, True),
                         (live.iteration, live.variant, live.exposed.value))
        self.assertEqual(3, context.get_pending_count())
        self.assert_published(
            context, self.holdout_exposure(11, "holdout_h", 0),
            self.exposure(2, "exp_g", NORMAL_VARIANT),
            self.holdout_exposure(11, "holdout_h", 1))

    def test_holdout_becoming_applicable_after_refresh_still_fires_for_overridden_experiment(self):
        context = self.create_context(
            context_data([experiment(1, "exp_override_late_holdout")]),
            overrides={"exp_override_late_holdout": 3})
        self.assertEqual(3, context.get_treatment("exp_override_late_holdout"))
        self.assertEqual(1, context.get_pending_count())
        self.refresh(context, context_data(
            [self.covered(1, "exp_override_late_holdout", [11])],
            [holdout(11, "holdout_late", HOLDOUT_A_SEEDS)]))
        self.assertEqual(3, context.get_treatment("exp_override_late_holdout"))
        self.assertEqual(3, context.get_pending_count())
        own = self.exposure(1, "exp_override_late_holdout", 3, assigned=False,
                            overridden=True)
        self.assert_published(context, own, own,
                              self.holdout_exposure(11, "holdout_late", 0))

    def test_variable_path_holdout_exposure_schedules_flush_without_any_other_event(self):
        suppressed = self.covered(1, "exp_var_flush_suppressed", [11])
        suppressed["variants"][1]["config"] = '{"flush_key":"from_suppressed"}'
        assigned = experiment(2, "exp_var_flush_assigned")
        assigned["variants"][1]["config"] = '{"flush_key":"from_assigned"}'
        context = self.create_context(
            context_data([suppressed, assigned], [self.holdout_a()]),
            publish_delay=0.01)
        # The assigned candidate's exposure is already queued, so only the
        # holdout exposure reached through the variable path is new.
        context.get_treatment("exp_var_flush_assigned")
        self.client.wait_for_publish(1)
        self.assertEqual("from_assigned",
                         context.get_variable_value("flush_key", "default"))
        self.client.wait_for_publish(2)
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual([self.holdout_exposure(11, "holdout_a", 0)],
                         self.exposure_tuples(
                             self.client.published[-1].exposures))

    def test_set_data_does_not_mutate_caller_supplied_holdout_ids_array(self):
        data = context_data(
            [self.covered(1, "exp_no_mutate_in", [12, 11]),
             experiment(2, "exp_no_mutate_not_covered")], [self.holdout_a()])
        caller_ids = data.experiments[0].holdoutIds
        context = self.create_context(data)
        self.assertEqual(0, context.get_treatment("exp_no_mutate_in"))
        self.assertEqual(NORMAL_VARIANT,
                         context.get_treatment("exp_no_mutate_not_covered"))
        self.assertEqual([12, 11], caller_ids)
        self.assertIs(caller_ids, data.experiments[0].holdoutIds)

    # --- Assignment rules beat holdout suppression (scenario 305)

    def test_matching_assignment_rule_wins_over_holdout_suppression(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_rules", [11],
                          assignmentRules=US_RULE)],
            [self.holdout_a(name="holdout_rules_suppression")]))
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_holdout_rules"))
        self.assert_published(
            context,
            self.exposure(1, "exp_holdout_rules", 1, assigned=False,
                          rule_override=True),
            self.holdout_exposure(11, "holdout_rules_suppression", 0))

    def test_matching_split_rule_wins_over_holdout_suppression(self):
        rules = json.dumps({"rules": [{
            "name": "Everyone", "type": "split", "conditions": None,
            "environments": [], "percentages": "0/100"}]})
        context = self.create_context(context_data(
            [self.covered(1, "exp_split_rule", [11], assignmentRules=rules)],
            [self.holdout_a()]))
        self.assertEqual(1, context.peek_treatment("exp_split_rule"))
        self.assertEqual(1, context.get_treatment("exp_split_rule"))
        self.assertEqual(2, context.get_pending_count())

    def test_held_out_unit_is_suppressed_when_rule_does_not_match(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_rules", [11],
                          assignmentRules=US_RULE)], [self.holdout_a()]))
        context.set_attribute("country", "GB")
        self.assertEqual(0, context.get_treatment("exp_holdout_rules"))
        self.assertEqual(1, context.get_pending_count())
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_holdout_rules"))
        self.assertEqual(2, context.get_pending_count())

    def test_held_out_unit_is_suppressed_again_when_rule_stops_matching(self):
        context = self.create_context(context_data(
            [self.covered(1, "exp_holdout_rules", [11],
                          assignmentRules=US_RULE)], [self.holdout_a()]))
        context.set_attribute("country", "US")
        self.assertEqual(1, context.get_treatment("exp_holdout_rules"))
        self.assertEqual(2, context.get_pending_count())
        context.set_attribute("country", "GB")
        self.assertEqual(0, context.get_treatment("exp_holdout_rules"))
        self.assertEqual(0, context.peek_treatment("exp_holdout_rules"))
        self.assertEqual(2, context.get_pending_count())

    def test_variable_value_on_held_out_rule_won_experiment(self):
        context = self.create_context(context_data(
            [with_variables(self.covered(1, "exp_holdout_rules", [11],
                                         assignmentRules=US_RULE), "color")],
            [self.holdout_a(name="holdout_rules_suppression")]))
        context.set_attribute("country", "US")
        self.assertEqual("treatment",
                         context.get_variable_value("color", "default"))
        self.assert_published(
            context,
            self.holdout_exposure(11, "holdout_rules_suppression", 0),
            self.exposure(1, "exp_holdout_rules", 1, assigned=False,
                          rule_override=True))

    def test_shared_variable_key_prefers_rule_won_over_suppressed_experiment(self):
        context = self.create_context(context_data(
            [with_variables(self.covered(1, "exp_held_out", [11]), "color"),
             with_variables(self.covered(2, "exp_rule_won", [11],
                                         assignmentRules=US_RULE), "color")],
            [self.holdout_a()]))
        context.set_attribute("country", "GB")
        self.assertEqual("control",
                         context.peek_variable_value("color", "default"))
        context.set_attribute("country", "US")
        self.assertEqual("treatment",
                         context.peek_variable_value("color", "default"))

    def test_shared_variable_key_prefers_earlier_assigned_over_later_rule_won_experiment(self):
        context = self.create_context(context_data(
            [with_variables(experiment(1, "exp_assigned", split=[1.0, 0.0]),
                            "color"),
             with_variables(experiment(2, "exp_rule_won",
                                       assignmentRules=US_RULE), "color")],
            []))
        context.set_attribute("country", "US")
        self.assertEqual("control",
                         context.peek_variable_value("color", "default"))
        self.assertEqual(1, context.peek_treatment("exp_rule_won"))


if __name__ == "__main__":
    unittest.main()
