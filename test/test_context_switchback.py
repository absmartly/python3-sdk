"""Switchback serving through Context, ported from the Java SDK's
ContextSwitchbackTest (java-sdk main, core-api/src/test/java/com/absmartly/
sdk/ContextSwitchbackTest.java, merged in java-sdk#15). The rules are in the
Java SDK's SWITCHBACK.md.
"""
import json
import sys
import threading
import time
import unittest
from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.context import Assignment
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.internal.variant_assigner import VariantAssigner
from sdk.utils import hash_unit
from test.holdout_fixtures import context_data, holdout
from test.switchback_fixtures import (
    ANCHOR, ASSIGN_VARIANT_1, ASSIGN_VARIANT_2, CLUSTER_KEY, CLUSTER_PATH,
    DAY, EXPECTED_10_ARMS, EXPECTED_2_ARMS, EXPECTED_3_ARMS, HOUR,
    SEED_HI, SEED_LO, STRICT_GOLD_AUDIENCE, UID, UID_3_ARMS, UID_HASH,
    UID_HASH_3_ARMS, UNIT_TYPE, CountingAudienceMatcher, SwitchbackFixture,
    clusters, draw, exposure, rule_exposure, strict_mismatch_exposure,
    switchback, unit_twin)

ASSIGN_VARIANT_1_TO_US = json.dumps({"rules": [{
    "type": "assign", "environments": [],
    "conditions": {"and": [{"eq": [{"var": "country"}, {"value": "US"}]}]},
    "variant": 1}]})
TRUE_AUDIENCE = json.dumps({"filter": [{"value": True}]})


def sb_holdout(split):
    # Holdout 11 for UID under seed (13, 111); split decides whether UID is
    # held out.
    return holdout(11, "holdout_a", (13, 111), unit_type=UNIT_TYPE,
                   split=split)


class SwitchbackTestCase(SwitchbackFixture, unittest.TestCase):
    def setUp(self):
        self.set_up_fixture()

    def resolution(self, context, name="exp_sb"):
        """The cached slot at the clock's current reading (the Java SDK's
        switchbackResolutionForTest seam)."""
        experiment = context.get_experiment(name)
        period = experiment.switchback.period(self.clock.now)
        return context.assignment_cache.get(
            name if period is None else (name, period))


class ContextSwitchbackTest(SwitchbackTestCase):

    def test_cluster_identity_is_the_raw_cluster_value(self):
        self.assertEqual(UID_HASH, hash_unit(UID))
        context = self.create_context([switchback(arm_count=3)])
        served = self.peek_schedule(context, "exp_sb")

        self.assertEqual(EXPECTED_3_ARMS, served)
        self.assertNotEqual(UID_HASH_3_ARMS, served)
        self.assertNotEqual(UID_3_ARMS, served)
        hashed_key = hash_unit(CLUSTER_KEY)
        self.assertEqual([draw(CLUSTER_KEY, i, 3) for i in range(12)], served)
        self.assertNotEqual([draw(hashed_key, i, 3) for i in range(12)],
                            served)

    def test_serves_two_three_and_ten_arm_permutations(self):
        context = self.create_context([
            switchback(1, "exp_2", 2), switchback(2, "exp_3", 3),
            switchback(3, "exp_10", 10)])
        self.assertEqual(EXPECTED_2_ARMS, self.peek_schedule(context, "exp_2"))
        self.assertEqual(EXPECTED_3_ARMS, self.peek_schedule(context, "exp_3"))
        self.assertEqual(EXPECTED_10_ARMS,
                         self.peek_schedule(context, "exp_10"))

    def test_one_hour_boundary_at_exact_edge_milliseconds(self):
        context = self.create_context([switchback()])
        for now, expected in ((ANCHOR - 1, 0), (ANCHOR, EXPECTED_2_ARMS[0]),
                              (ANCHOR + HOUR - 1, EXPECTED_2_ARMS[0]),
                              (ANCHOR + HOUR, EXPECTED_2_ARMS[1]),
                              (ANCHOR + 3 * HOUR - 1, EXPECTED_2_ARMS[2]),
                              (ANCHOR + 3 * HOUR, EXPECTED_2_ARMS[3])):
            self.clock.now = now
            self.assertEqual(expected, context.peek_treatment("exp_sb"), now)

    def test_twenty_four_hour_boundary_at_exact_edge_milliseconds(self):
        context = self.create_context([switchback(period_ms=DAY)])
        for now, expected in ((ANCHOR - 1, 0), (ANCHOR, EXPECTED_2_ARMS[0]),
                              (ANCHOR + HOUR, EXPECTED_2_ARMS[0]),
                              (ANCHOR + DAY - 1, EXPECTED_2_ARMS[0]),
                              (ANCHOR + DAY, EXPECTED_2_ARMS[1]),
                              (ANCHOR + 4 * DAY - 1, EXPECTED_2_ARMS[3]),
                              (ANCHOR + 4 * DAY, EXPECTED_2_ARMS[4])):
            self.clock.now = now
            self.assertEqual(expected, context.peek_treatment("exp_sb"), now)

    def test_unaligned_start_is_unservable_and_pre_anchor_is_ineligible(self):
        start = ANCHOR + 1_234_567
        context = self.create_context([
            switchback(1, "exp_aligned", switchbackStartAt=ANCHOR + HOUR),
            switchback(2, "exp_unaligned", switchbackStartAt=start)])
        for now in (ANCHOR, start - 1, start, ANCHOR + HOUR - 1):
            self.clock.now = now
            self.assertEqual(0, context.get_treatment("exp_aligned"))
            self.assertEqual(0, context.get_treatment("exp_unaligned"))
        self.assertEqual(0, context.get_pending_count())
        for i in range(1, 4):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(EXPECTED_2_ARMS[i - 1],
                             context.get_treatment("exp_aligned"))
            self.assertEqual(0, context.get_treatment("exp_unaligned"))
            self.clock.now = start + i * HOUR
            self.assertEqual(0, context.get_treatment("exp_unaligned"))

        self.assert_published(
            context,
            exposure(1, "exp_aligned", EXPECTED_2_ARMS[0], ANCHOR + HOUR),
            exposure(1, "exp_aligned", EXPECTED_2_ARMS[1], ANCHOR + 2 * HOUR),
            exposure(1, "exp_aligned", EXPECTED_2_ARMS[2], ANCHOR + 3 * HOUR))

    def test_unaligned_or_out_of_range_anchor_is_unservable(self):
        max_anchor = 253_402_300_800_000
        long_max = (1 << 63) - 1
        for start_at in (ANCHOR + 1, ANCHOR - 1, ANCHOR + 30 * 60_000,
                         ANCHOR + HOUR - 1, -HOUR, -1, max_anchor,
                         max_anchor + HOUR, long_max - (long_max % HOUR),
                         ANCHOR + 0.5, str(ANCHOR), True, None):
            self.client.published.clear()
            # The cluster attribute is set at creation, before every read.
            self.clock.now = 0
            context = self.create_context([switchback(
                switchbackStartAt=start_at)])
            for now in (0, ANCHOR, ANCHOR + 2 * HOUR + 1, max_anchor + DAY):
                self.clock.now = now
                self.assertEqual(0, context.get_treatment("exp_sb"),
                                 (start_at, now))
                self.assertEqual(0, context.get_variable_value("sb.arm", -1))
            self.assertEqual(0, context.get_pending_count(), start_at)
            context.publish()
            self.assertEqual([], self.client.published, start_at)

        # In-range hour-aligned anchors, including 0 and the last hour
        # before the bound, serve. A whole JSON float is read as its integer
        # (Jackson's float-to-long coercion in the Java SDK).
        for start_at in (0, ANCHOR, max_anchor - HOUR, float(ANCHOR)):
            self.clock.now = start_at + HOUR
            context = self.create_context([switchback(
                switchbackStartAt=start_at)])
            self.assertEqual(EXPECTED_2_ARMS[1],
                             context.get_treatment("exp_sb"), start_at)
            self.assertEqual(1, context.get_pending_count())

    def test_period_index_is_exact_integer_division(self):
        # A 1 ms period from anchor 0 at 2**53 + 1: a float division would
        # round the period index to 2**53.
        now = (1 << 53) + 1
        self.clock.now = 0
        context = self.create_context([switchback(
            arm_count=2, switchbackStartAt=0, switchbackPeriodMs=1)])
        self.clock.now = now
        self.assertNotEqual(draw(CLUSTER_KEY, now, 2),
                            draw(CLUSTER_KEY, now - 1, 2))
        self.assertEqual(draw(CLUSTER_KEY, now, 2),
                         context.peek_treatment("exp_sb"))

    def test_unservable_periods_are_silent(self):
        for period_ms in (None, 0, -HOUR, 1.5, "3600000", True):
            context = self.create_context([switchback(
                switchbackPeriodMs=period_ms)])
            for i in range(3):
                self.clock.now = ANCHOR + i * HOUR
                self.assertEqual(0, context.get_treatment("exp_sb"),
                                 period_ms)
            self.assertEqual(0, context.get_pending_count(), period_ms)
        context = self.create_context([switchback(
            split=[1.0], variants=[{"name": "A", "config": None}])])
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())

    def test_null_start_at_never_falls_back_to_unit_assignment(self):
        context = self.create_context([switchback(switchbackStartAt=None)])
        for i in range(4):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(0, context.get_treatment("exp_sb"))
            # Variant 0's own config, like any ineligible assignment.
            self.assertEqual(0, context.get_variable_value("sb.arm", -1))
        self.assertEqual(0, context.get_pending_count())

    def test_one_exposure_per_period_across_a_rollover(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())
        self.clock.now = ANCHOR + HOUR - 1
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(EXPECTED_2_ARMS[0], context.peek_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

        self.clock.now = ANCHOR + HOUR
        self.assertEqual(EXPECTED_2_ARMS[1], context.peek_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(EXPECTED_2_ARMS[1], context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())
        self.clock.now = ANCHOR + HOUR + 30 * 60_000
        self.assertEqual(EXPECTED_2_ARMS[1], context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

        self.assert_published(
            context,
            exposure(1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + 10),
            exposure(1, "exp_sb", EXPECTED_2_ARMS[1], ANCHOR + HOUR))

    def test_variable_lookups_follow_the_period(self):
        context = self.create_context([switchback(arm_count=3)])
        self.assertEqual({"sb.arm": ["exp_sb"]},
                         context.get_variable_keys_all())
        self.assertEqual(["exp_sb"], context.get_experiments())
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(EXPECTED_3_ARMS[i],
                             context.peek_variable_value("sb.arm", -1))
            self.assertEqual(EXPECTED_3_ARMS[i],
                             context.get_variable_value("sb.arm", -1))
            self.assertEqual(EXPECTED_3_ARMS[i],
                             context.get_variable_value("sb.arm", -1))
            self.assertEqual(EXPECTED_3_ARMS[i],
                             context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

    def test_missing_cluster_unit_is_unassigned_without_fallback(self):
        # No unit of a linked type: the experiment does not apply and
        # records nothing. unitType is never a fallback.
        context = self.create_context([switchback(unitType="user_id")],
                                      units={"user_id": UID})
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(0, context.peek_treatment("exp_sb"))
            self.assertEqual(0, context.get_treatment("exp_sb"))
            self.assertEqual(-1, context.get_variable_value("sb.arm", -1))
        self.assertEqual(0, context.get_pending_count())

        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(EXPECTED_2_ARMS[2], context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[2], ANCHOR + 2 * HOUR))

    def test_overridden_absent_slot_reresolves_on_set_unit(self):
        context = self.create_context([switchback()], units={},
                                      overrides={"exp_sb": 1})
        self.clock.now = ANCHOR + 5
        self.assertEqual(1, context.peek_treatment("exp_sb"))
        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", 1, ANCHOR + 5, assigned=False, overridden=True))

    def test_full_on_serves_the_full_on_variant_in_every_period(self):
        context = self.create_context([switchback(arm_count=3,
                                                  fullOnVariant=2)])
        for i in range(4):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assert_published(context, *[
            exposure(1, "exp_sb", 2, ANCHOR + i * HOUR, full_on=True)
            for i in range(4)])

    def test_override_and_custom_assignment_win_in_every_period(self):
        context = self.create_context([
            switchback(1, "exp_override", 3), switchback(2, "exp_custom", 3)])
        context.set_override("exp_override", 7)
        context.set_custom_assignment("exp_custom", 2)
        expected = []
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(7, context.get_treatment("exp_override"))
            self.assertEqual(2, context.get_treatment("exp_custom"))
            expected += [
                exposure(1, "exp_override", 7, self.clock.now,
                         assigned=False, overridden=True),
                exposure(2, "exp_custom", 2, self.clock.now, custom=True)]
        self.assert_published(context, *expected)

    def test_traffic_miss_wins_over_a_custom_assignment(self):
        # Traffic is checked before the custom assignment (scenario 416's
        # exp_sb_custom_traffic_miss): the miss is recorded, custom=false.
        context = self.create_context([switchback(
            arm_count=3, trafficSplit=[1.0, 0.0])],
            custom_assignments={"exp_sb": 2})
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(1, "exp_sb", 0, ANCHOR,
                                                eligible=False))

    def test_full_on_refresh_re_resolves_the_slot(self):
        context = self.create_context([switchback(arm_count=3)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(EXPECTED_3_ARMS[0], context.get_treatment("exp_sb"))
        self.refresh_to(context, switchback(arm_count=3, fullOnVariant=2))
        self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assert_published(
            context, exposure(1, "exp_sb", EXPECTED_3_ARMS[0], ANCHOR + 5),
            exposure(1, "exp_sb", 2, ANCHOR + 5, full_on=True))

    def test_custom_assignment_change_re_resolves_the_slot(self):
        context = self.create_context([switchback(arm_count=3)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(EXPECTED_3_ARMS[0], context.get_treatment("exp_sb"))
        context.set_custom_assignment("exp_sb", 2)
        self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

    def test_traffic_eligibility_is_cluster_sticky(self):
        eligible_count = 0
        ineligible_count = 0
        for u in range(24):
            self.client.published.clear()
            self.clock.now = ANCHOR
            context = self.create_context(
                [switchback(1, "exp_sb", trafficSplit=[0.5, 0.5]),
                 unit_twin(2, "exp_unit", trafficSplit=[0.5, 0.5])],
                units={UNIT_TYPE: f"store_{u}"})
            context.get_treatment("exp_unit")
            for i in range(4):
                self.clock.now = ANCHOR + i * HOUR
                context.get_treatment("exp_sb")
            exposures = self.publish_event(context).exposures
            self.assertEqual(5, len(exposures))
            twin_eligible = exposures[0].eligible
            for e in exposures[1:]:
                self.assertEqual("exp_sb", e.name)
                self.assertEqual(twin_eligible, e.eligible)
                if not twin_eligible:
                    self.assertEqual(0, e.variant)
            if twin_eligible:
                eligible_count += 1
            else:
                ineligible_count += 1
        self.assertGreater(eligible_count, 0)
        self.assertGreater(ineligible_count, 0)

    def test_unit_experiments_are_unaffected(self):
        context = self.create_context([
            switchback(randomizationType="unit"),
            switchback(2, "exp_absent", randomizationType=None),
            switchback(3, "exp_other", randomizationType="Switchback")])
        variants = [context.get_treatment(name)
                    for name in ("exp_sb", "exp_absent", "exp_other")]
        for i in range(1, 6):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(variants, [
                context.get_treatment(name)
                for name in ("exp_sb", "exp_absent", "exp_other")])
        self.assertEqual(3, context.get_pending_count())

    def test_refresh_invalidates_on_grid_fields_only(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

        self.refresh_to(context, switchback(
            switchbackBurnInDurationMs=600_000,
            switchbackBurnOutDurationMs=300_000,
            switchbackCarryoverDurationMs=900_000,
            switchbackEstimand="other"))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

        # Same period index 0 under both grids, so only the identity
        # comparison can invalidate.
        self.refresh_to(context, switchback(period_ms=2 * HOUR))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

        self.refresh_to(context, switchback(
            period_ms=2 * HOUR, switchbackDesignType="other_design"))
        context.get_treatment("exp_sb")
        self.assertEqual(3, context.get_pending_count())

        self.refresh_to(context, switchback(period_ms=2 * HOUR,
                                            randomizationType="unit"))
        context.get_treatment("exp_sb")
        self.assertEqual(4, context.get_pending_count())

        self.refresh_to(context, switchback(period_ms=2 * HOUR))
        context.get_treatment("exp_sb")
        self.assertEqual(5, context.get_pending_count())

        # The cluster map (types, paths and their order) and the allow-list
        # are identity.
        path_changed = clusters(UNIT_TYPE, "'store_key'")
        self.refresh_to(context, switchback(period_ms=2 * HOUR,
                                            switchbackClusters=path_changed))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(6, context.get_pending_count())

        link_added = clusters(UNIT_TYPE, "'store_key'", "device_id", "city")
        self.refresh_to(context, switchback(period_ms=2 * HOUR,
                                            switchbackClusters=link_added))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(7, context.get_pending_count())

        reordered = clusters("device_id", "city", UNIT_TYPE, "'store_key'")
        self.refresh_to(context, switchback(period_ms=2 * HOUR,
                                            switchbackClusters=reordered))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(8, context.get_pending_count())

        self.refresh_to(context, switchback(
            period_ms=2 * HOUR, switchbackClusters=reordered,
            switchbackClusterValues=[CLUSTER_KEY]))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(9, context.get_pending_count())

        # An unrelated unitType edit is not identity: switchbacks never
        # read it.
        self.refresh_to(context, switchback(
            period_ms=2 * HOUR, switchbackClusters=reordered,
            switchbackClusterValues=[CLUSTER_KEY], unitType="anything"))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(9, context.get_pending_count())

    def test_seed_and_split_refreshes_keep_the_cached_slot(self):
        context = self.create_context([switchback(arm_count=3)])
        self.clock.now = ANCHOR + 10
        self.assertEqual(EXPECTED_3_ARMS[0], context.get_treatment("exp_sb"))
        self.refresh_to(context, switchback(arm_count=3, seedHi=99,
                                            split=[0.2, 0.3, 0.5]))
        self.assertEqual(EXPECTED_3_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())
        # The next period uses the new seed.
        self.clock.now = ANCHOR + HOUR
        self.assertEqual(draw(CLUSTER_KEY, 1, 3, (99 << 32) |
                              (SEED_LO & 0xffffffff)),
                         context.get_treatment("exp_sb"))

    def test_refresh_setting_start_at_starts_the_grid(self):
        context = self.create_context([switchback(switchbackStartAt=None)])
        self.clock.now = ANCHOR + 10
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

    def test_holdout_suppression_and_exposure_span_periods(self):
        # Holdouts never apply to a switchback: a holdout that would hold
        # the unit out neither suppresses it nor records its own exposure.
        context = self.create_context(
            [switchback(holdoutIds=[11])], holdouts=[sb_holdout([0.1, 0.9])])
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(EXPECTED_2_ARMS[i],
                             context.get_treatment("exp_sb"))
            self.assertEqual(EXPECTED_2_ARMS[i],
                             context.get_variable_value("sb.arm", -1))
        self.assert_published(context, *[
            exposure(1, "exp_sb", EXPECTED_2_ARMS[i], ANCHOR + i * HOUR)
            for i in range(3)])

    def test_holdout_is_never_resolved_for_a_switchback(self):
        context = self.create_context(
            [switchback(holdoutIds=[11]),
             unit_twin(2, "exp_unit", holdoutIds=[11])],
            holdouts=[sb_holdout([0.1, 0.9])])
        context.get_treatment("exp_sb")
        self.assertIsNone(context.get_experiment("exp_sb").holdouts)
        self.assertEqual({}, context._holdout_assignments)
        # The unit experiment sharing the holdout is still held out by it.
        self.assertEqual(0, context.get_treatment("exp_unit"))
        self.assert_published(
            context, exposure(1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR),
            exposure(11, "holdout_a", 0, ANCHOR))

    def test_assignment_rule_overrides_the_schedule(self):
        for u in range(10):
            self.client.published.clear()
            self.clock.now = ANCHOR - 1
            context = self.create_context(
                [switchback(assignmentRules=ASSIGN_VARIANT_1)],
                units={UNIT_TYPE: f"user-{u}"})
            self.assertEqual(1, context.get_treatment("exp_sb"))
            self.assertEqual(1, context.get_variable_value("sb.arm", -1))
            for i in range(4):
                self.clock.now = ANCHOR + i * HOUR
                self.assertEqual(1, context.get_treatment("exp_sb"))
            self.assert_published(
                context, rule_exposure("exp_sb", 1, ANCHOR - 1),
                *[rule_exposure("exp_sb", 1, ANCHOR + i * HOUR)
                  for i in range(4)])

    def test_unservable_only_replaces_the_draw(self):
        context = self.create_context([
            switchback(1, "sb_full_on", switchbackStartAt=None,
                       fullOnVariant=1),
            switchback(2, "sb_rules", switchbackPeriodMs=0,
                       assignmentRules=ASSIGN_VARIANT_1),
            switchback(3, "sb_unaligned_rules", switchbackStartAt=ANCHOR + 1,
                       assignmentRules=ASSIGN_VARIANT_1)],
            units={UNIT_TYPE: "15"})
        self.assertEqual(1, context.get_treatment("sb_full_on"))
        self.assertEqual(1, context.get_treatment("sb_rules"))
        self.assertEqual(1, context.get_treatment("sb_unaligned_rules"))
        self.assert_published(
            context, exposure(1, "sb_full_on", 1, ANCHOR, full_on=True),
            rule_exposure("sb_rules", 1, ANCHOR, id=2),
            rule_exposure("sb_unaligned_rules", 1, ANCHOR, id=3))

    def test_assignment_rules_do_not_apply_to_an_ineligible_cluster(self):
        context = self.create_context([switchback(
            assignmentRules=ASSIGN_VARIANT_1,
            switchbackClusterValues=["other-store"])])
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())

    def test_split_rule_randomizes_over_the_serving_unit(self):
        rules = json.dumps({"rules": [{"type": "split", "environments": [],
                                       "percentages": "50/50"}]})
        ones = 0
        for u in range(32):
            self.client.published.clear()
            uid = f"store-{u}"
            expected = VariantAssigner(bytearray(hash_unit(uid).encode())) \
                .assign([0.5, 0.5], SEED_HI, SEED_LO)
            context = self.create_context(
                [switchback(unitType="user_id", assignmentRules=rules)],
                units={UNIT_TYPE: uid, "user_id": "fixed-user"})
            self.assertEqual(expected, context.get_treatment("exp_sb"), uid)
            self.assert_published(context,
                                  rule_exposure("exp_sb", expected, ANCHOR))
            ones += expected
        self.assertTrue(0 < ones < 32)

    def test_audience_strict_mismatch_is_recorded_as_control(self):
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True)])
        self.clock.now = ANCHOR + HOUR
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context, strict_mismatch_exposure(ANCHOR + HOUR))

    def test_audience_strict_mismatch_exposure_serializes_exactly(self):
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True)])
        self.assertEqual(1, EXPECTED_2_ARMS[1])
        self.clock.now = ANCHOR + HOUR + 5
        context.get_treatment("exp_sb")
        self.clock.now = ANCHOR + HOUR + 9
        event = self.publish_event(context)
        self.assertEqual(
            '{"attributes": [{"name": "store_key", "setAt": %d, '
            '"value": "store-42"}], '
            '"exposures": [{"assigned": false, "audienceMismatch": true, '
            '"custom": false, "eligible": true, "exposedAt": %d, '
            '"fullOn": false, "id": 1, "name": "exp_sb", '
            '"overridden": false, "ruleOverride": false, '
            '"unit": "store_id", "variant": 0}], '
            '"hashed": true, "historic": false, "publishedAt": %d, '
            '"units": [{"type": "store_id", "uid": "%s"}]}'
            % (ANCHOR, ANCHOR + HOUR + 5, ANCHOR + HOUR + 9, UID_HASH),
            self.serialized(event))

    def test_audience_strict_mismatch_before_the_anchor_is_recorded(self):
        self.clock.now = ANCHOR - 1
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True)])
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context, strict_mismatch_exposure(ANCHOR - 1))

    def test_strict_mismatch_on_unservable_schedule_is_recorded(self):
        self.clock.now = ANCHOR + HOUR + 3
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True,
            switchbackStartAt=None)])
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context,
                              strict_mismatch_exposure(ANCHOR + HOUR + 3))

    def test_strict_mismatch_on_legacy_path_records_nothing(self):
        for cluster_map in (None, clusters(UNIT_TYPE, "'geo")):
            self.clock.now = ANCHOR + HOUR + 3
            context = self.create_context([switchback(
                audience=STRICT_GOLD_AUDIENCE, audienceStrict=True,
                switchbackClusters=cluster_map)])
            self.assertEqual(0, context.get_treatment("exp_sb"), cluster_map)
            self.assertEqual(0, context.get_pending_count(), cluster_map)

    def test_strict_mismatch_gives_way_on_a_shared_key(self):
        unit = unit_twin(2, "exp_unit", fullOnVariant=1, variants=[
            {"name": "A", "config": json.dumps({"sb.arm": 10})},
            {"name": "B", "config": json.dumps({"sb.arm": 11})}])
        self.clock.now = ANCHOR + HOUR + 3
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True), unit])
        self.assertEqual({"sb.arm": ["exp_sb", "exp_unit"]},
                         context.get_variable_keys_all())
        self.assertEqual(11, context.peek_variable_value("sb.arm", -1))
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(11, context.get_variable_value("sb.arm", -1))
        # The Python SDK exposes every experiment visited on a shared key
        # (v0.3.0 behaviour): the strict mismatch is recorded too.
        self.assert_published(
            context, strict_mismatch_exposure(ANCHOR + HOUR + 3),
            exposure(2, "exp_unit", 1, ANCHOR + HOUR + 3, full_on=True))

    def test_strict_mismatch_alone_on_a_key_returns_default(self):
        self.clock.now = ANCHOR + HOUR + 3
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True)])
        self.assertEqual(-1, context.peek_variable_value("sb.arm", -1))
        self.assertEqual(-1, context.get_variable_value("sb.arm", -1))
        self.assertEqual(1, context.get_pending_count())

    def test_traffic_miss_on_eligible_cluster_is_recorded(self):
        context = self.create_context([
            switchback(1, "exp_miss", trafficSplit=[1.0, 0.0]),
            switchback(2, "exp_cluster_ineligible", trafficSplit=[1.0, 0.0],
                       switchbackClusterValues=["other-store"])])
        self.clock.now = ANCHOR + 2 * HOUR + 3
        self.assertEqual(0, context.get_treatment("exp_miss"))
        self.assertEqual(0, context.get_treatment("exp_cluster_ineligible"))
        self.assert_published(context, exposure(
            1, "exp_miss", 0, ANCHOR + 2 * HOUR + 3, eligible=False))

    def test_custom_field_values_and_unit_lookups_work(self):
        context = self.create_context([switchback()])
        self.assertEqual(UID, context.get_unit(UNIT_TYPE))
        self.assertEqual([], context.get_custom_field_keys())
        self.assertIsNone(context.get_custom_field_value("exp_sb", "missing"))

    def test_per_period_cache_is_bounded(self):
        # Each experiment keeps entries for at most its two latest periods.
        context = self.create_context([switchback()])
        for i in range(50):
            self.clock.now = ANCHOR + i * HOUR
            context.get_treatment("exp_sb")
        self.assertEqual({("exp_sb", 48), ("exp_sb", 49)},
                         set(context.assignment_cache))
        self.assertEqual(50, context.get_pending_count())

    def test_unit_type_is_not_used_for_switchback_assignment(self):
        context = self.create_context([switchback(unitType="user_id")],
                                      units={UNIT_TYPE: UID, "user_id": "u1"})
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(EXPECTED_2_ARMS[i],
                             context.get_treatment("exp_sb"))
        self.assertEqual([UNIT_TYPE] * 3,
                         [e[2] for e in self.published_exposures(context)])

    def test_publish_payload_has_no_new_fields(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 5
        context.get_treatment("exp_sb")
        self.clock.now = ANCHOR + HOUR + 7
        context.get_treatment("exp_sb")
        self.clock.now = ANCHOR + HOUR + 9
        event = self.publish_event(context)

        def exposure_json(variant, exposed_at):
            return ('{"assigned": true, "audienceMismatch": false, '
                    '"custom": false, "eligible": true, "exposedAt": %d, '
                    '"fullOn": false, "id": 1, "name": "exp_sb", '
                    '"overridden": false, "ruleOverride": false, '
                    '"unit": "store_id", "variant": %d}'
                    % (exposed_at, variant))

        # The cluster attribute is published timestamped, as before: the
        # Collector re-resolves the cluster at exposedAt from it.
        self.assertEqual(
            '{"attributes": [{"name": "store_key", "setAt": %d, '
            '"value": "store-42"}], "exposures": [%s, %s], '
            '"hashed": true, "historic": false, "publishedAt": %d, '
            '"units": [{"type": "store_id", "uid": "%s"}]}'
            % (ANCHOR, exposure_json(EXPECTED_2_ARMS[0], ANCHOR + 5),
               exposure_json(EXPECTED_2_ARMS[1], ANCHOR + HOUR + 7),
               ANCHOR + HOUR + 9, UID_HASH),
            self.serialized(event))
        self.assertNotEqual(EXPECTED_2_ARMS[0], EXPECTED_2_ARMS[1])

    def test_periods_published_across_flushes_stay_one_per_period(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR
        context.get_treatment("exp_sb")
        context.publish()
        self.clock.now = ANCHOR + 1
        context.get_treatment("exp_sb")
        self.assertEqual(0, context.get_pending_count())
        self.clock.now = ANCHOR + HOUR
        context.get_treatment("exp_sb")
        context.publish()
        self.assertEqual(
            [EXPECTED_2_ARMS[0], EXPECTED_2_ARMS[1]],
            [e.variant for event in self.client.published
             for e in event.exposures])

    def test_treatment_exposure_is_stamped_with_the_resolution_instant(self):
        # The clock crosses into period 1 between resolution (the first
        # read) and any later read; the exposure keeps the instant that
        # selected period 0.
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + HOUR
        self.clock.next_read = ANCHOR + HOUR - 1
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + HOUR - 1))

    def test_variable_exposure_is_stamped_with_the_resolution_instant(self):
        # Holdouts never fire through a switchback.
        context = self.create_context([switchback(holdoutIds=[11])],
                                      holdouts=[sb_holdout([0.0, 1.0])])
        self.clock.now = ANCHOR + HOUR
        self.clock.next_read = ANCHOR + HOUR - 1
        self.assertEqual(EXPECTED_2_ARMS[0],
                         context.get_variable_value("sb.arm", -1))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + HOUR - 1))

    def test_exposure_after_peek_uses_the_exposing_calls_instant(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        self.assertEqual(EXPECTED_2_ARMS[0], context.peek_treatment("exp_sb"))
        self.clock.now = ANCHOR + 20 * 60_000
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + 20 * 60_000))

    def test_unit_exposure_timing_is_unchanged(self):
        # Unit experiments keep their single clock reading, at enqueue time,
        # also in a payload with switchbacks.
        context = self.create_context([switchback(randomizationType="unit"),
                                       switchback(2, "exp_other")])
        reads = []
        millis = self.clock.millis
        self.clock.millis = lambda: reads.append(1) or millis()
        self.clock.now = ANCHOR + HOUR
        variant = context.get_treatment("exp_sb")
        self.assertEqual(1, len(reads))
        self.clock.millis = millis
        self.assert_published(context, exposure(1, "exp_sb", variant,
                                                ANCHOR + HOUR))

    def test_historic_exposed_at_selects_the_period(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 5 * HOUR
        self.assertEqual(EXPECTED_2_ARMS[1], context.get_treatment(
            "exp_sb", exposed_at=ANCHOR + HOUR + 1))
        self.assertEqual(EXPECTED_2_ARMS[5], context.get_treatment("exp_sb"))
        self.assert_published(
            context, exposure(1, "exp_sb", EXPECTED_2_ARMS[1],
                              ANCHOR + HOUR + 1),
            exposure(1, "exp_sb", EXPECTED_2_ARMS[5], ANCHOR + 5 * HOUR))

    def test_grid_refresh_to_a_lower_index_exposes_once(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 99 * HOUR
        context.get_treatment("exp_sb")
        self.clock.now = ANCHOR + 100 * HOUR
        context.get_treatment("exp_sb")
        self.assertEqual(2, context.get_pending_count())
        self.refresh_to(context, switchback(
            switchbackStartAt=ANCHOR + 100 * HOUR))
        for _ in range(3):
            self.assertEqual(EXPECTED_2_ARMS[0],
                             context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

    def test_period_length_refresh_to_a_lower_index_exposes_once(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 100 * HOUR
        context.get_treatment("exp_sb")
        self.clock.now = ANCHOR + 101 * HOUR
        context.get_treatment("exp_sb")
        self.refresh_to(context, switchback(period_ms=200 * HOUR))
        context.get_treatment("exp_sb")
        context.get_treatment("exp_sb")
        self.assertEqual(3, context.get_pending_count())

    def test_clock_rewind_reexposes_an_evicted_period_at_most_once(self):
        context = self.create_context([switchback()])
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            context.get_treatment("exp_sb")
        self.assertEqual(3, context.get_pending_count())

        self.clock.now = ANCHOR
        for _ in range(3):
            self.assertEqual(EXPECTED_2_ARMS[0],
                             context.get_treatment("exp_sb"))
        self.assertEqual(4, context.get_pending_count())

        # Retained {0, 2}: period 2 is still deduplicated, 1 was evicted.
        self.clock.now = ANCHOR + 2 * HOUR
        context.get_treatment("exp_sb")
        self.assertEqual(4, context.get_pending_count())
        self.clock.now = ANCHOR + HOUR
        for _ in range(3):
            self.assertEqual(EXPECTED_2_ARMS[1],
                             context.get_treatment("exp_sb"))
        self.assertEqual(5, context.get_pending_count())

        exposures = self.published_exposures(context)
        self.assertEqual(exposure(1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR),
                         exposures[3])
        self.assertEqual(exposure(1, "exp_sb", EXPECTED_2_ARMS[1],
                                  ANCHOR + HOUR), exposures[4])

    def test_override_is_reresolved_when_the_grid_changes(self):
        holdouts = [sb_holdout([0.0, 1.0])]
        context = self.create_context(
            [switchback(arm_count=3, holdoutIds=[11])], holdouts=holdouts)
        context.set_override("exp_sb", 2)
        self.clock.now = ANCHOR + 10
        self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_variable_value("sb.arm", -1))
        self.assertEqual(1, context.get_pending_count())

        # Same index 0 under the new period length; variant 2 now carries a
        # different value.
        regridded = switchback(arm_count=3, period_ms=2 * HOUR,
                               holdoutIds=[11])
        regridded["variants"][2]["config"] = json.dumps({"sb.arm": 22})
        self.refresh_to(context, regridded, holdouts=holdouts)
        self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assertEqual(22, context.get_variable_value("sb.arm", -1))
        self.assertEqual(2, context.get_pending_count())
        self.assert_published(context, *[
            exposure(1, "exp_sb", 2, ANCHOR + 10, assigned=False,
                     overridden=True)] * 2)

    def test_switchback_to_unit_to_identical_switchback_reresolves(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())
        self.refresh_to(context, switchback(randomizationType="unit"))
        context.get_treatment("exp_sb")
        self.assertEqual(2, context.get_pending_count())
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

    def test_removed_and_restored_switchback_reresolves(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        context.get_treatment("exp_sb")
        self.refresh_to(context)
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

    def test_pre_anchor_slot_is_dropped_when_the_grid_changes(self):
        grid_a = switchback(switchbackStartAt=ANCHOR + 10 * HOUR)
        context = self.create_context([grid_a])
        self.clock.now = ANCHOR + 10
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())
        self.refresh_to(context, grid_a)
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(0, context.get_variable_value("sb.arm", -1))
        self.assertEqual(1, context.get_pending_count())

    def test_transitions_without_an_intervening_lookup_still_reresolve(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        context.get_treatment("exp_sb")
        self.assertEqual(1, context.get_pending_count())

        self.refresh_to(context, switchback(randomizationType="unit"))
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

        self.refresh_to(context)
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

        self.refresh_to(context, switchback(switchbackDesignType="other"))
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(4, context.get_pending_count())

        self.refresh_to(context, switchback())
        context.get_treatment("exp_sb")
        self.assertEqual(4, context.get_pending_count())

    def test_failed_refresh_then_restored_switchback_reresolves(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        context.get_treatment("exp_sb")
        context.publish()
        context.set_data_failed(RuntimeError("down"))
        self.refresh_to(context, switchback())
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

    def test_stale_rule_transition_evaluates_the_rules_twice(self):
        matcher = CountingAudienceMatcher()
        context = self.create_context([switchback(
            randomizationType="unit", assignmentRules=ASSIGN_VARIANT_1_TO_US)],
            audience_matcher=matcher)
        context.peek_treatment("exp_sb")
        self.assertEqual(1, matcher.rule_evaluations)
        context.set_attribute("country", "US")
        matcher.rule_evaluations = 0
        self.assertEqual(1, context.peek_treatment("exp_sb"))
        self.assertEqual(2, matcher.rule_evaluations)
        self.assertEqual(1, context.peek_treatment("exp_sb"))
        self.assertEqual(2, matcher.rule_evaluations)

    def test_legacy_switchback_unit_type_change_is_identity(self):
        # A legacy (missing or unreadable cluster map) switchback serves
        # under its declared unitType, so a unitType change is identity.
        context = self.create_context([switchback(switchbackClusters=None)],
                                      units={UNIT_TYPE: UID, "user_id": "u1"})
        self.clock.now = ANCHOR + 10
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_variable_value("sb.arm", -1))
        self.assertEqual(UNIT_TYPE, self.resolution(context).unit_type)

        self.refresh_to(context, switchback(switchbackClusters=None,
                                            unitType="other"))
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(-1, context.get_variable_value("sb.arm", -1))

        self.refresh_to(context, switchback(switchbackClusters=None,
                                            unitType="user_id"))
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_variable_value("sb.arm", -1))
        resolution = self.resolution(context)
        self.assertEqual("user_id", resolution.unit_type)
        self.assertFalse(resolution.eligible)
        self.assertTrue(resolution.switchback_silent)
        self.assertEqual(0, context.get_pending_count())

    def test_rules_are_not_reevaluated_for_an_ineligible_or_absent_slot(self):
        matcher = CountingAudienceMatcher()
        absent_map = clusters("device_id", CLUSTER_PATH)
        context = self.create_context([
            switchback(1, "exp_ineligible", assignmentRules=ASSIGN_VARIANT_1,
                       switchbackClusterValues=["other-store"]),
            switchback(2, "exp_absent", assignmentRules=ASSIGN_VARIANT_1,
                       switchbackClusters=absent_map)],
            audience_matcher=matcher)
        self.clock.now = ANCHOR + 10
        self.assertEqual(0, context.get_treatment("exp_ineligible"))
        self.assertEqual(0, context.get_treatment("exp_absent"))
        self.assertEqual(0, matcher.rule_evaluations)

        context.set_attribute("x", 1)
        changed = json.dumps({"rules": [{"type": "assign", "environments": [],
                                         "variant": 1, "name": "changed"}]})
        self.refresh_to(
            context,
            switchback(1, "exp_ineligible", assignmentRules=changed,
                       switchbackClusterValues=["other-store"]),
            switchback(2, "exp_absent", assignmentRules=changed,
                       switchbackClusters=absent_map))
        self.assertEqual(0, context.get_treatment("exp_ineligible"))
        self.assertEqual(0, context.get_treatment("exp_absent"))
        self.assertEqual(0, matcher.rule_evaluations)
        self.assertEqual(0, context.get_pending_count())

    def test_in_period_rule_refresh_keeps_the_variant_and_exposes_once(self):
        context = self.create_context([switchback(
            assignmentRules=ASSIGN_VARIANT_1)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(1, context.get_treatment("exp_sb"))
        context.set_attribute("tier", "x")
        self.refresh_to(context, switchback(assignmentRules=json.dumps(
            {"rules": [{"type": "assign", "environments": [], "variant": 1,
                        "conditions": {"and": [{"eq": [
                            {"var": "tier"}, {"value": "x"}]}]}}]})))
        self.clock.now = ANCHOR + 6
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assert_published(context, rule_exposure("exp_sb", 1, ANCHOR + 5))

    def test_pre_anchor_traffic_miss_is_silent(self):
        # The cluster attribute is set before the call, so the cluster
        # itself is eligible.
        self.clock.now = ANCHOR - 1
        context = self.create_context([switchback(trafficSplit=[1.0, 0.0])])
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())
        self.clock.now = ANCHOR
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(1, "exp_sb", 0, ANCHOR,
                                                eligible=False))

    def test_legacy_override_uses_the_declared_unit_type(self):
        context = self.create_context([
            switchback(1, "exp_missing_map", unitType="user_id",
                       switchbackClusters=None),
            switchback(2, "exp_unreadable_map", unitType="user_id",
                       switchbackClusters=clusters(UNIT_TYPE,
                                                   "'unterminated"))])
        context.set_override("exp_missing_map", 1)
        context.set_override("exp_unreadable_map", 1)
        self.clock.now = ANCHOR + 5
        self.assertEqual(1, context.get_treatment("exp_missing_map"))
        self.assertEqual(1, context.get_treatment("exp_unreadable_map"))
        self.assert_published(
            context,
            exposure(1, "exp_missing_map", 1, ANCHOR + 5, unit="user_id",
                     assigned=False, overridden=True),
            exposure(2, "exp_unreadable_map", 1, ANCHOR + 5, unit="user_id",
                     assigned=False, overridden=True))

    def test_override_without_a_serving_unit_uses_the_first_linked_type(self):
        context = self.create_context([switchback(
            unitType="user_id",
            switchbackClusters=clusters("device_id", "x", UNIT_TYPE, "y"))],
            units={}, overrides={"exp_sb": 1})
        self.clock.now = ANCHOR + 5
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", 1, ANCHOR + 5, unit="device_id", assigned=False,
            overridden=True))

    def test_rule_won_and_traffic_miss_exposures_serialize_exactly(self):
        context = self.create_context([
            switchback(1, "exp_rule", assignmentRules=ASSIGN_VARIANT_1),
            switchback(2, "exp_miss", trafficSplit=[1.0, 0.0])])
        self.clock.now = ANCHOR + 5
        context.get_treatment("exp_rule")
        context.get_treatment("exp_miss")
        self.clock.now = ANCHOR + 9
        event = self.publish_event(context)
        self.assertEqual(
            '{"attributes": [{"name": "store_key", "setAt": %d, '
            '"value": "store-42"}], "exposures": ['
            '{"assigned": false, "audienceMismatch": false, "custom": false, '
            '"eligible": true, "exposedAt": %d, "fullOn": false, "id": 1, '
            '"name": "exp_rule", "overridden": false, "ruleOverride": true, '
            '"unit": "store_id", "variant": 1}, '
            '{"assigned": true, "audienceMismatch": false, "custom": false, '
            '"eligible": false, "exposedAt": %d, "fullOn": false, "id": 2, '
            '"name": "exp_miss", "overridden": false, "ruleOverride": false, '
            '"unit": "store_id", "variant": 0}], '
            '"hashed": true, "historic": false, "publishedAt": %d, '
            '"units": [{"type": "store_id", "uid": "%s"}]}'
            % (ANCHOR, ANCHOR + 5, ANCHOR + 5, ANCHOR + 9, UID_HASH),
            self.serialized(event))

    def test_queue_exposure_hook_sees_the_resolution_instant(self):
        context = self.create_context([switchback()])
        hooked = []
        original = context.queue_exposure

        def queue_exposure(assignment):
            hooked.append((assignment.name, assignment.exposedAt))
            return original(assignment)

        context.queue_exposure = queue_exposure
        self.clock.now = ANCHOR + HOUR
        self.clock.next_read = ANCHOR + HOUR - 1
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual([("exp_sb", ANCHOR + HOUR - 1)], hooked)
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + HOUR - 1))

    def test_unit_reads_call_a_one_argument_expose_override(self):
        # Context._expose(assignment) keeps its one-argument call for unit
        # experiments, also in a payload with switchbacks.
        context = self.create_context([switchback(),
                                       unit_twin(2, "exp_unit")])
        seen = []
        original = context._expose

        def expose(assignment):
            seen.append(assignment.name)
            return original(assignment)

        context._expose = expose
        context.get_treatment("exp_unit")
        context.get_treatment("exp_sb")
        self.assertEqual(["exp_unit"], seen)
        self.assertEqual(2, context.get_pending_count())

    def test_unchanged_revalidation_is_recorded_on_the_slot(self):
        # After set_attribute, one revalidation keeps the slot and records
        # the attribute sequence, so later reads do not evaluate again.
        matcher = CountingAudienceMatcher()
        context = self.create_context([switchback(
            assignmentRules=ASSIGN_VARIANT_1_TO_US)], audience_matcher=matcher)
        self.clock.now = ANCHOR + 5
        slot = context.get_assignment("exp_sb")
        self.assertEqual(1, matcher.rule_evaluations)
        context.set_attribute("country", "PT")
        for _ in range(5):
            self.assertEqual(EXPECTED_2_ARMS[0],
                             context.peek_treatment("exp_sb"))
        self.assertEqual(2, matcher.rule_evaluations)
        self.assertIs(slot, context.get_assignment("exp_sb"))

    def test_rule_won_slot_ignores_its_audience_on_revalidation(self):
        # A rule-won slot never consulted the audience (Java audienceMatches
        # returns early), so an attribute change keeps it and its exposure.
        context = self.create_context([switchback(
            assignmentRules=ASSIGN_VARIANT_1, audience=STRICT_GOLD_AUDIENCE,
            audienceStrict=True)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(1, context.get_treatment("exp_sb"))
        slot = context.get_assignment("exp_sb")
        slot.audience_mismatch = True
        context.set_attribute("tier", "gold")
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assertIs(slot, context.get_assignment("exp_sb"))
        self.assert_published(context, rule_exposure("exp_sb", 1, ANCHOR + 5))

    def test_pre_anchor_slot_refreshed_to_full_on_unit(self):
        # The pre-anchor slot uses the bare experiment name, which the unit
        # path also caches under: the stale slot is dropped first.
        context = self.create_context([switchback(
            switchbackStartAt=ANCHOR + HOUR)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())
        self.refresh_to(context, switchback(randomizationType="unit",
                                            fullOnVariant=1))
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(1, "exp_sb", 1, ANCHOR + 5,
                                                full_on=True))
        # Its slots are gone, so its reads are back on the unit path.
        self.assertEqual(frozenset(), context._switchback_names)

    def test_pre_anchor_slot_refreshed_to_identical_unit(self):
        # The bare-name pre-anchor slot is still cached when the refresh
        # makes the name a unit experiment; the first read drops it.
        context = self.create_context([switchback(
            switchbackStartAt=ANCHOR + HOUR)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(0, context.peek_treatment("exp_sb"))
        # Same id, unit type, iteration, full-on and traffic, so the unit
        # path alone would take the silent slot as current.
        self.refresh_to(context, unit_twin(1, "exp_sb"))
        context.get_treatment("exp_sb")
        exposures = self.published_exposures(context)
        self.assertEqual(1, len(exposures))
        self.assertTrue(exposures[0][5] and exposures[0][6])

    def test_override_value_change_re_resolves_the_slot(self):
        context = self.create_context([switchback(arm_count=3)])
        self.clock.now = ANCHOR + 5
        context.set_override("exp_sb", 1)
        self.assertEqual(1, context.get_treatment("exp_sb"))
        context.set_override("exp_sb", 2)
        self.assertEqual(2, context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

    def test_exposing_a_silent_slot_on_a_closing_context_raises(self):
        context = self.create_context([switchback(
            switchbackClusterValues=["other-store"])])
        self.clock.now = ANCHOR + 5
        slot = context.get_assignment("exp_sb")
        self.assertTrue(slot.switchback_silent)
        context.closing.set(True)
        with self.assertRaises(RuntimeError):
            context._expose_at(slot, ANCHOR + 5)
        self.assertFalse(slot.exposed.value)

    def test_a_rejecting_queue_exposure_hook_sees_the_retrys_reading(self):
        context = self.create_context([switchback()])
        hooked = []
        original = context.queue_exposure

        def queue_exposure(assignment):
            hooked.append(assignment.exposedAt)
            if len(hooked) == 1:
                return False
            return original(assignment)

        context.queue_exposure = queue_exposure
        self.clock.now = ANCHOR + 20
        self.clock.next_read = ANCHOR + 10
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual([ANCHOR + 10, ANCHOR + 20], hooked)
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + 20))

    def test_closed_context_rejects_switchback_reads(self):
        context = self.create_context([switchback()])
        context.close()
        with self.assertRaises(RuntimeError):
            context.get_treatment("exp_sb")


class ExposureFlagParityTest(SwitchbackTestCase):
    """The SWITCHBACK.md "Exposure flags" table: the same branch on a unit
    experiment and on an eligible-cluster switchback publishes the same
    flags; only the unit and the variant can differ."""

    # assigned, eligible, overridden, fullOn, custom, audienceMismatch,
    # ruleOverride; then the variant at period 2 (3-arm draw 1).
    BRANCHES = {
        "override": ((False, True, True, False, False, False, False), 2),
        "override_over_strict": (
            (False, True, True, False, False, False, False), 2),
        "rule": ((False, True, False, False, False, False, True), 2),
        "rule_over_strict": (
            (False, True, False, False, False, False, True), 2),
        "strict": ((False, True, False, False, False, True, False), 0),
        "strict_over_full_on": (
            (False, True, False, False, False, True, False), 0),
        "strict_over_traffic_miss": (
            (False, True, False, False, False, True, False), 0),
        "non_strict": ((True, True, False, False, False, True, False),
                       EXPECTED_3_ARMS[2]),
        "full_on": ((True, True, False, True, False, False, False), 2),
        "traffic_miss": ((True, False, False, False, False, False, False), 0),
        "custom": ((True, True, False, False, True, False, False), 2),
        "draw": ((True, True, False, False, False, False, False),
                 EXPECTED_3_ARMS[2]),
    }

    @staticmethod
    def configure(branch, data):
        if branch in ("override_over_strict", "rule_over_strict", "strict",
                      "strict_over_full_on", "strict_over_traffic_miss"):
            data["audience"] = STRICT_GOLD_AUDIENCE
            data["audienceStrict"] = True
        if branch == "non_strict":
            data["audience"] = STRICT_GOLD_AUDIENCE
        if branch in ("strict_over_full_on", "full_on"):
            data["fullOnVariant"] = 2
        if branch in ("strict_over_traffic_miss", "traffic_miss"):
            data["trafficSplit"] = [1.0, 0.0]
        if branch in ("rule", "rule_over_strict"):
            data["assignmentRules"] = ASSIGN_VARIANT_2
        return data

    def expose_once(self, data, branch):
        self.client.published.clear()
        context = self.create_context([self.configure(branch, data)])
        if branch in ("override", "override_over_strict"):
            context.set_override("exp_parity", 2)
        elif branch == "custom":
            context.set_custom_assignment("exp_parity", 2)
        context.get_treatment("exp_parity")
        exposures = self.published_exposures(context)
        self.assertEqual(1, len(exposures), branch)
        return exposures[0]

    def test_exposure_flags_match_a_unit_experiment_for_every_branch(self):
        self.clock.now = ANCHOR + 2 * HOUR + 3
        self.assertEqual(1, EXPECTED_3_ARMS[2])
        for branch, (flags, variant) in self.BRANCHES.items():
            unit = self.expose_once(unit_twin(1, "exp_parity", 3), branch)
            sb = self.expose_once(switchback(1, "exp_parity", 3), branch)
            self.assertEqual(flags, unit[5:], "unit " + branch)
            self.assertEqual(flags, sb[5:], "switchback " + branch)
            self.assertEqual(variant, sb[3], "switchback variant " + branch)
            if branch not in ("draw", "non_strict"):
                self.assertEqual(variant, unit[3], "unit variant " + branch)
            self.assertEqual(unit[:3], sb[:3])
            self.assertEqual(unit[4], sb[4])


class SwitchbackConcurrencyTest(SwitchbackTestCase):

    class BarrierAudienceMatcher(AudienceMatcher):
        # Unlike Java, the read path only reports a slot stale; the audience
        # is re-checked on the write path, one reader at a time. Both
        # readers start together at `readers`, and the re-check is slowed
        # so the second one queues on the write lock behind the first.
        def __init__(self):
            super().__init__(DefaultAudienceDeserializer())
            self.evaluations = 0
            self.lock = threading.Lock()
            self.readers = threading.Barrier(2, timeout=10)

        def evaluate(self, audience, attributes):
            with self.lock:
                self.evaluations += 1
            time.sleep(0.05)
            return super().evaluate(audience, attributes)

    def test_concurrent_resolution_of_the_same_period_exposes_once(self):
        matcher = self.BarrierAudienceMatcher()
        context = self.create_context([switchback(audience=TRUE_AUDIENCE)],
                                      audience_matcher=matcher)
        self.clock.now = ANCHOR + HOUR + 10
        self.assertEqual(EXPECTED_2_ARMS[1], context.peek_treatment("exp_sb"))
        context.set_attribute("country", "PT")
        variants = [None, None]

        def read(i):
            matcher.readers.wait()
            variants[i] = context.get_treatment("exp_sb")

        workers = [threading.Thread(target=read, args=(i,), daemon=True)
                   for i in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertFalse(matcher.readers.broken)
        self.assertEqual([EXPECTED_2_ARMS[1]] * 2, variants)
        self.assertEqual(1, context.get_pending_count())
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[1], ANCHOR + HOUR + 10))

    def test_concurrent_set_attribute_does_not_move_the_slot(self):
        context = self.create_context([switchback(
            switchbackClusters=clusters(UNIT_TYPE, "city"))])
        self.clock.now = ANCHOR + HOUR + 10
        context.set_attribute("city", "Lisboa")
        expected = draw("Lisboa", 1, 2)
        self.assertEqual(expected, context.peek_treatment("exp_sb"))
        stop = threading.Event()

        def write():
            while not stop.is_set():
                context.set_attribute("city", "Faro")

        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        try:
            results = [context.get_treatment("exp_sb") for _ in range(200)]
        finally:
            stop.set()
            writer.join(10)
        self.assertEqual({expected}, set(results))
        self.assertEqual(1, context.get_pending_count())

    def test_concurrent_resolution_and_set_attribute(self):
        # The cluster attribute changes before both readers re-resolve the
        # slot and a writer keeps setting it meanwhile: the slot keeps the
        # key read at its first resolution (Lisboa, variant 1 in period 1;
        # Faro is 0 there, so a re-read key would show).
        self.assertEqual((1, 0), (draw("Lisboa", 1, 2), draw("Faro", 1, 2)))
        matcher = self.BarrierAudienceMatcher()
        context = self.create_context([switchback(
            audience=TRUE_AUDIENCE,
            switchbackClusters=clusters(UNIT_TYPE, "city"))],
            audience_matcher=matcher)
        self.clock.now = ANCHOR + HOUR + 10
        context.set_attribute("city", "Lisboa")
        self.assertEqual(1, context.peek_treatment("exp_sb"))
        context.set_attribute("country", "PT")
        context.set_attribute("city", "Faro")
        variants = [None, None]
        failures = []
        readers_done = threading.Event()

        def read(i):
            try:
                matcher.readers.wait()
                variants[i] = context.get_treatment("exp_sb")
            except Exception as e:  # pragma: no cover - reported below
                failures.append(e)

        def write():
            writes = 0
            while (not readers_done.is_set() or writes < 1000) and \
                    writes < 100_000:
                context.set_attribute("city", "Faro")
                writes += 1

        readers = [threading.Thread(target=read, args=(i,), daemon=True)
                   for i in range(2)]
        writer = threading.Thread(target=write, daemon=True)
        for worker in readers + [writer]:
            worker.start()
        for worker in readers:
            worker.join(10)
            self.assertFalse(worker.is_alive())
        readers_done.set()
        writer.join(10)
        self.assertFalse(writer.is_alive())
        self.assertEqual([], failures)
        self.assertFalse(matcher.readers.broken)
        self.assertEqual([1, 1], variants)
        self.assertEqual(1, context.get_pending_count())
        self.assert_published(context, exposure(
            1, "exp_sb", 1, ANCHOR + HOUR + 10, audience_mismatch=False))

    class RefreshingAudienceMatcher(AudienceMatcher):
        # Refreshes the context from inside audience evaluation, which runs
        # under the context lock.
        def __init__(self):
            super().__init__(DefaultAudienceDeserializer())
            self.context = None
            self.refresh_on_next_evaluation = False

        def evaluate(self, audience, attributes):
            if self.refresh_on_next_evaluation:
                self.refresh_on_next_evaluation = False
                self.context.refresh()
            return super().evaluate(audience, attributes)

    def stub_refresh(self, data, on_another_thread):
        if not on_another_thread:
            self.client.refresh_data = data
            return
        client = self.client

        def get_context_data():
            future = Future()
            threading.Thread(target=lambda: (time.sleep(0.05),
                                             future.set_result(data)),
                             daemon=True).start()
            return future

        client.get_context_data = get_context_data

    def treatment_within(self, context, name, timeout=10):
        result = []
        worker = threading.Thread(
            target=lambda: result.append(context.get_treatment(name)),
            daemon=True)
        worker.start()
        worker.join(timeout)
        self.assertFalse(worker.is_alive(),
                         "refresh from audience evaluation deadlocked")
        return result[0]

    def refresh_from_audience_revalidation_completes(self, on_another_thread):
        experiment = switchback(audience=TRUE_AUDIENCE)
        matcher = self.RefreshingAudienceMatcher()
        context = self.create_context([experiment], audience_matcher=matcher)
        matcher.context = context
        self.stub_refresh(context_data([experiment]), on_another_thread)
        self.clock.now = ANCHOR + 5
        primed = context.get_treatment("exp_sb")
        context.set_attribute("country", "PT")
        matcher.refresh_on_next_evaluation = True
        self.assertEqual(primed, self.treatment_within(context, "exp_sb"))
        context.wait_until_ready()
        self.assertEqual(1, context.get_pending_count())

    def test_refresh_in_revalidation_sync_no_deadlock(self):
        self.refresh_from_audience_revalidation_completes(False)

    def test_refresh_in_revalidation_async_no_deadlock(self):
        self.refresh_from_audience_revalidation_completes(True)

    def test_refresh_during_the_first_read_keeps_the_name_routed(self):
        # The refresh turns the switchback into a unit experiment while its
        # first read is resolving, before its epoch exists: the stale slot
        # must still be dropped on the next read.
        experiment = switchback(audience=TRUE_AUDIENCE,
                                switchbackStartAt=ANCHOR + HOUR)
        matcher = self.RefreshingAudienceMatcher()
        context = self.create_context([experiment], audience_matcher=matcher)
        matcher.context = context
        self.client.refresh_data = context_data(
            [unit_twin(1, "exp_sb", split=[0.0, 1.0])])
        matcher.refresh_on_next_evaluation = True
        self.clock.now = ANCHOR + 5
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

    def test_refresh_during_a_first_in_period_read_keeps_the_name_routed(self):
        # The post-anchor twin: the period slot of the first read must still
        # be dropped, so the unit experiment exposes once, not again on the
        # next refresh.
        matcher = self.RefreshingAudienceMatcher()
        context = self.create_context([switchback(audience=TRUE_AUDIENCE)],
                                      audience_matcher=matcher)
        matcher.context = context
        unit = unit_twin(1, "exp_sb", split=[0.0, 1.0])
        self.client.refresh_data = context_data([unit])
        matcher.refresh_on_next_evaluation = True
        self.clock.now = ANCHOR + 5
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.refresh_to(context, unit)
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

    def test_name_update_on_a_first_read_is_atomic_with_set_data(self):
        # A set_data that runs while the first read adds its name must not
        # lose the switchback it installs.
        context = self.create_context([switchback()])
        installed = []
        # Set once the refresh thread reaches set_data's install step:
        # either it is about to block on the data lock the name update holds
        # or, without that lock, it installs immediately.
        reached_install = threading.Event()
        data_lock = context.data_lock
        acquire_write = data_lock.acquire_write

        def acquire_write_marked():
            if threading.current_thread() is not threading.main_thread():
                reached_install.set()
            acquire_write()

        data_lock.acquire_write = acquire_write_marked

        class Names(frozenset):
            def __or__(names, other):
                if not installed:
                    installed.append(True)
                    worker = threading.Thread(target=self.refresh_to, args=(
                        context, switchback(), switchback(2, "exp_new")))
                    worker.start()
                    self.assertTrue(reached_install.wait(10))
                    # Without the lock the install completes right away; with
                    # it this short join just times out.
                    worker.join(0.2)
                    installed.append(worker)
                return frozenset(names) | other

        context._switchback_names = Names(context._switchback_names)
        self.clock.now = ANCHOR + 5
        context.get_treatment("exp_sb")
        installed[1].join(10)
        self.assertFalse(installed[1].is_alive())
        self.assertIn("exp_new", context._switchback_names)
        self.assertEqual(draw(CLUSTER_KEY, 0, 2),
                         context.get_treatment("exp_new"))

    def test_refresh_in_first_resolution_async_no_deadlock(self):
        experiment = switchback(audience=TRUE_AUDIENCE)
        matcher = self.RefreshingAudienceMatcher()
        context = self.create_context([experiment], audience_matcher=matcher)
        matcher.context = context
        self.stub_refresh(context_data([experiment]), True)
        matcher.refresh_on_next_evaluation = True
        self.clock.now = ANCHOR + 5
        self.treatment_within(context, "exp_sb")
        self.assertEqual(1, context.get_pending_count())


class JervasionRoundOneTest(SwitchbackTestCase):

    def test_unit_to_switchback_refresh_between_routing_and_assignment(self):
        # A refresh installs a switchback after get_assignment routed the
        # name to the unit path: the unit path must hand over, never apply
        # the switchback definition as a unit experiment.
        # A full-on switchback with no cluster value is a silent control, so
        # serving 1 (or exposing at all) means the unit path applied it.
        # With full-on 0 the switchback matches the cached unit slot on every
        # field the unit path compares, so only the switchback check keeps
        # the read path from serving (and exposing) the stale unit slot.
        for primed, full_on in ((True, 1), (False, 1), (True, 0)):
            context = self.create_context([unit_twin(1, "exp_sb")],
                                          cluster_attribute=False)
            self.clock.now = ANCHOR + 5
            if primed:
                context.peek_treatment("exp_sb")
            refresh = context_data([switchback(fullOnVariant=full_on)])
            swapped = []
            acquire_read = context.context_lock.acquire_read

            def refresh_then_read():
                if not swapped:
                    swapped.append(True)
                    self.client.refresh_data = refresh
                    context.refresh()
                acquire_read()

            context.context_lock.acquire_read = refresh_then_read
            self.assertEqual(0, context.get_treatment("exp_sb"), primed)
            context.context_lock.acquire_read = acquire_read
            self.assertEqual(0, context.get_treatment("exp_sb"), primed)
            self.assertEqual(0, context.get_pending_count(), primed)

    def test_zero_timestamps_are_used_as_given(self):
        # Anchor 0: a read at 0 is in period 0 even when the clock moves on.
        self.clock.now = 0
        context = self.create_context([switchback(switchbackStartAt=0)])
        self.clock.now = HOUR
        self.clock.next_read = 0
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], 0))
        self.clock.now = 0
        context = self.create_context([switchback(switchbackStartAt=0)])
        self.clock.now = HOUR
        self.assertEqual(EXPECTED_2_ARMS[0],
                         context.get_treatment("exp_sb", exposed_at=0))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], 0))

    def test_a_raising_queue_exposure_hook_leaves_no_stale_time(self):
        context = self.create_context([switchback()])
        calls = []
        original = context.queue_exposure

        def queue_exposure(assignment):
            calls.append(assignment.exposedAt)
            if len(calls) == 1:
                raise RuntimeError("hook down")
            return original(assignment)

        context.queue_exposure = queue_exposure
        self.clock.now = ANCHOR + 10
        with self.assertRaises(RuntimeError):
            context.get_treatment("exp_sb")
        self.assertIsNone(context.get_assignment("exp_sb").exposedAt)
        self.clock.now = ANCHOR + 20
        context.get_treatment("exp_sb")
        self.assertEqual([ANCHOR + 10, ANCHOR + 20], calls)
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + 20))

    def test_peek_then_attribute_update_is_reconstructible(self):
        # The Collector resolves the cluster from the published attributes
        # at exposedAt (latest setAt <= exposedAt): that must be the cluster
        # whose draw the exposure carries.
        context = self.create_context([switchback(
            arm_count=3, switchbackClusters=clusters(UNIT_TYPE, "city"))],
            cluster_attribute=False)
        self.assertNotEqual(draw("11", 0, 3), draw("10", 0, 3))
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "11")
        self.assertEqual(draw("11", 0, 3), context.peek_treatment("exp_sb"))
        self.clock.now = ANCHOR + 20
        context.set_attribute("city", "10")
        self.assertEqual(draw("11", 0, 3), context.get_treatment("exp_sb"))
        event = self.publish_event(context)
        exposed_at = event.exposures[0].exposedAt
        visible = [a for a in event.attributes
                   if a.name == "city" and a.setAt <= exposed_at]
        latest = max(visible, key=lambda a: a.setAt).value
        self.assertEqual("11", latest)
        self.assertEqual(draw(latest, 0, 3), event.exposures[0].variant)
        self.assertEqual(0, (exposed_at - ANCHOR) // HOUR)

    def test_peek_then_unchanged_cluster_keeps_the_exposing_time(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        context.peek_treatment("exp_sb")
        self.clock.now = ANCHOR + 20
        context.set_attribute("other", "x")
        context.get_treatment("exp_sb")
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + 20))

    def test_a_long_digit_path_segment_does_not_reject_the_context(self):
        long_path = "geo/" + "9" * 4301 + "/city"
        context = self.create_context([
            switchback(switchbackClusters=clusters(UNIT_TYPE, long_path)),
            unit_twin(2, "exp_unit", fullOnVariant=1)])
        self.assertTrue(context.is_ready())
        self.assertFalse(context.is_failed())
        self.assertEqual(1, context.get_treatment("exp_unit"))
        self.assertEqual(0, context.get_treatment("exp_sb"))

    def test_an_unreadable_switchback_is_isolated_from_the_context(self):
        class Hostile(dict):
            def items(self):
                raise RuntimeError("unreadable")

        data = context_data([switchback(), unit_twin(2, "exp_unit",
                                                     fullOnVariant=1)])
        data.experiments[0].switchbackClusters = Hostile(store_id="x")
        context = self.create_context([])
        self.client.refresh_data = data
        context.refresh()
        self.assertFalse(context.is_failed())
        self.assertEqual(1, context.get_treatment("exp_unit"))
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

    def test_deep_identity_metadata_does_not_reject_the_refresh(self):
        # 900 levels decode with the default deserializer on every supported
        # Python (json.dumps cannot build it on 3.9), and exceed what a
        # recursive identity encoder survives once install adds its frames.
        depth = 900
        fields = json.dumps(switchback(switchbackDesignType="DEEP"))
        fields = fields.replace('"DEEP"', "[" * depth + '"x"' + "]" * depth)
        payload = '{"experiments": [%s, %s]}' % (
            fields, json.dumps(unit_twin(2, "exp_unit", fullOnVariant=1)))
        data = DefaultContextDataDeserializer().deserialize(
            payload.encode(), 0, len(payload))
        self.assertIsNotNone(data)
        context = self.create_context([unit_twin(2, "exp_unit")])
        self.client.refresh_data = data
        context.refresh()
        self.assertFalse(context.is_failed())
        self.assertEqual(1, context.get_treatment("exp_unit"))
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.client.refresh_data = DefaultContextDataDeserializer() \
            .deserialize(payload.encode(), 0, len(payload))
        context.refresh()
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())


class JervasionRoundTwoTest(SwitchbackTestCase):

    def test_eligible_handoff_keeps_the_requested_period_time(self):
        context = self.create_context([unit_twin(1, "exp_sb")])
        self.clock.now = ANCHOR + HOUR
        acquire = context.context_lock.acquire_read
        changed = []

        def refresh_before_lock():
            if not changed:
                changed.append(True)
                self.refresh_to(context, switchback())
            acquire()

        context.context_lock.acquire_read = refresh_before_lock
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment(
            "exp_sb", exposed_at=ANCHOR))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR))

    def test_two_refresh_handoffs_never_return_none(self):
        context = self.create_context([unit_twin(1, "exp_sb")])
        original_unit = context._get_unit_assignment
        original_sb = context._get_switchback_assignment
        changes = []

        def unit(name, at):
            if not changes:
                changes.append("sb")
                self.refresh_to(context, switchback())
            return original_unit(name, at)

        def sb(name, at, now):
            if changes == ["sb"]:
                changes.append("unit")
                unit_data = unit_twin(1, "exp_sb", fullOnVariant=1)
                self.refresh_to(context, unit_data)
            return original_sb(name, at, now)

        context._get_unit_assignment = unit
        context._get_switchback_assignment = sb
        self.assertEqual(1, context.peek_treatment("exp_sb"))
        self.assertEqual(["sb", "unit"], changes)

    def test_same_tick_cluster_writes_are_reconstructible(self):
        context = self.create_context([switchback(
            arm_count=3, switchbackClusters=clusters(UNIT_TYPE, "city"))],
            cluster_attribute=False)
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "11")
        first = context.peek_treatment("exp_sb")
        context.set_attribute("city", "10")
        self.clock.now += 20
        self.assertEqual(first, context.get_treatment("exp_sb"))
        event = self.publish_event(context)
        timestamp = event.exposures[0].exposedAt
        visible = [a for a in event.attributes if a.setAt <= timestamp]
        # Collector breaks ties by the last published write.
        selected = sorted(enumerate(visible),
                          key=lambda pair: (pair[1].setAt, pair[0]))[-1][1]
        self.assertEqual("11", selected.value)
        self.assertEqual(draw(selected.value, 0, 3), first)
        self.assertEqual([ANCHOR + 10, ANCHOR + 11],
                         [a.setAt for a in event.attributes])

    def test_overlapping_hook_failure_cannot_change_forwarded_time(self):
        context = self.create_context([switchback()])
        self.clock.now = ANCHOR + 10
        entered = threading.Event()
        resume = threading.Event()
        original = context.queue_exposure
        calls = []
        errors = []

        def hook(assignment):
            calls.append(assignment)
            if len(calls) == 1:
                entered.set()
                if not resume.wait(5):
                    raise AssertionError("forwarder not resumed")
                return original(assignment)
            raise RuntimeError("second hook failed")

        def first():
            try:
                context.get_treatment("exp_sb")
            except Exception as e:
                errors.append(e)

        context.queue_exposure = hook
        worker = threading.Thread(target=first, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(5))
        self.clock.now = ANCHOR + 20
        with self.assertRaises(RuntimeError):
            context.get_treatment("exp_sb")
        self.clock.now = ANCHOR + HOUR
        resume.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], errors)
        self.assertIsNot(calls[0], calls[1])
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[0], ANCHOR + 10))


class GatePassSixTest(SwitchbackTestCase):

    def test_renaming_a_linked_unit_type_is_a_new_epoch(self):
        # Same path, another unit type: only the map key changes.
        context = self.create_context(
            [switchback(switchbackClusters=clusters(UNIT_TYPE, CLUSTER_PATH))],
            units={UNIT_TYPE: UID, "user_id": "u1"})
        self.clock.now = ANCHOR + 5
        context.get_treatment("exp_sb")
        self.refresh_to(context, switchback(
            switchbackClusters=clusters("user_id", CLUSTER_PATH)))
        context.get_treatment("exp_sb")
        self.assertEqual([UNIT_TYPE, "user_id"],
                         [e[2] for e in self.published_exposures(context)])

    def test_set_unit_keeps_an_exposed_absent_override(self):
        # An overridden switchback with no linked unit is exposed under the
        # first linked type; setting that unit later must not expose again.
        context = self.create_context([switchback()], units={"other": "o"},
                                      overrides={"exp_sb": 1})
        self.clock.now = ANCHOR + 5
        self.assertEqual(1, context.get_treatment("exp_sb"))
        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(1, context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

    def test_absent_serving_is_read_again_on_replacement(self):
        # No linked unit at first: the override is exposed under the first
        # linked type (a_id). After set_unit("b_id") the replaced slot reads
        # the serving unit again and exposes under b_id; Java does the same.
        sources = clusters("a_id", CLUSTER_PATH, "b_id", CLUSTER_PATH)
        context = self.create_context(
            [switchback(switchbackClusters=sources)],
            units={"c_id": "c"}, overrides={"exp_sb": 1})
        self.clock.now = ANCHOR + 5
        context.get_treatment("exp_sb")
        context.set_unit("b_id", "b")
        context.set_override("exp_sb", 0)
        context.get_treatment("exp_sb")
        self.assertEqual(["a_id", "b_id"],
                         [e[2] for e in self.published_exposures(context)])

    def test_attribute_names_are_trimmed_like_java_only(self):
        # Java trim() removes code points up to U+0020, not U+00A0.
        context = self.create_context([switchback()],
                                      cluster_attribute=False,
                                      attributes={CLUSTER_PATH + "\xa0":
                                                  CLUSTER_KEY})
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())

    def test_an_int_too_long_to_render_gives_no_cluster_value(self):
        # Only CPythons with the int-to-text digit limit (3.9.14+, 3.10.7+)
        # refuse to render it; pin the default limit for the test.
        if not hasattr(sys, "set_int_max_str_digits"):
            self.skipTest("this CPython renders ints of any length")
        limit = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(4300)
        self.addCleanup(sys.set_int_max_str_digits, limit)
        context = self.create_context([switchback()],
                                      cluster_attribute=False,
                                      attributes={CLUSTER_PATH: 10 ** 5000})
        self.assertEqual(0, context.peek_treatment("exp_sb"))
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_variable_value("sb.arm", -1))
        self.assertEqual(0, context.get_pending_count())

    def test_unit_revalidation_hands_over_to_an_installed_switchback(self):
        # The refresh lands while the unit path revalidates a cached slot
        # after set_attribute (its write-lock branch).
        context = self.create_context(
            [unit_twin(1, "exp_sb", audience=TRUE_AUDIENCE)],
            cluster_attribute=False)
        self.clock.now = ANCHOR + 5
        context.peek_treatment("exp_sb")
        context.set_attribute("x", 1)
        refresh = context_data([switchback(fullOnVariant=0,
                                           audience=TRUE_AUDIENCE)])
        acquire_write = context.context_lock.acquire_write
        swapped = []

        def refresh_then_write():
            if not swapped:
                swapped.append(True)
                self.client.refresh_data = refresh
                context.refresh()
            acquire_write()

        context.context_lock.acquire_write = refresh_then_write
        self.assertEqual(0, context.get_treatment("exp_sb"))
        context.context_lock.acquire_write = acquire_write
        self.assertEqual(0, context.get_pending_count())


class NoSwitchbackCostTest(SwitchbackTestCase):

    def test_unit_reads_next_to_a_switchback_skip_the_switchback_path(self):
        unit = unit_twin(2, "exp_unit", variants=[
            {"name": "A", "config": json.dumps({"unit.arm": 0})},
            {"name": "B", "config": json.dumps({"unit.arm": 1})}])
        context = self.create_context([switchback(), unit])
        seen = []
        original = context._get_switchback_assignment

        def spy(name, *args):
            seen.append(name)
            return original(name, *args)

        context._get_switchback_assignment = spy
        context.get_treatment("exp_unit")
        context.peek_treatment("exp_unit")
        context.get_variable_value("unit.arm", -1)
        context.peek_variable_value("unit.arm", -1)
        self.assertEqual([], seen)
        context.get_treatment("exp_sb")
        self.assertEqual(["exp_sb"], seen)

    def test_assignment_switchback_fields_are_class_defaults(self):
        fields = {"switchback", "switchback_generation", "switchback_serving",
                  "switchback_custom", "switchback_silent"}
        self.assertEqual(set(), fields & set(vars(Assignment())))

    def test_two_pre_anchor_switchbacks_refreshed_to_unit_experiments(self):
        # Reading the first after the refresh drops its slots and prunes the
        # names; the second still has pending slots and must stay routed.
        context = self.create_context([
            switchback(1, "a", switchbackStartAt=ANCHOR + HOUR),
            switchback(2, "b", switchbackStartAt=ANCHOR + HOUR)])
        self.clock.now = ANCHOR + 5
        self.assertEqual(0, context.get_treatment("a"))
        self.assertEqual(0, context.get_treatment("b"))
        self.refresh_to(context, unit_twin(1, "a", split=[0.0, 1.0]),
                        unit_twin(2, "b", split=[0.0, 1.0]))
        self.assertEqual(1, context.get_treatment("a"))
        self.assertEqual(1, context.get_treatment("b"))
        self.assertEqual(2, context.get_pending_count())

    def test_no_switchbacks_never_takes_the_switchback_path(self):
        context = self.create_context([unit_twin(1, "exp_unit")])
        self.assertEqual(frozenset(), context._switchback_names)
        calls = []
        context._get_switchback_assignment = \
            lambda *args: calls.append(args)
        context.clock = self.clock
        self.clock.next_read = None
        reads_before = []
        original_millis = self.clock.millis

        def counting_millis():
            reads_before.append(1)
            return original_millis()

        self.clock.millis = counting_millis
        context.get_treatment("exp_unit")
        context.peek_treatment("exp_unit")
        context.get_variable_value("sb.arm", -1)
        self.assertEqual([], calls)
        # One reading, at enqueue time, exactly as before switchbacks.
        self.assertEqual(1, len(reads_before))

    def test_switchback_fields_on_a_unit_experiment_publish_identically(self):
        fields = {k: v for k, v in switchback().items()
                  if k.startswith("switchback")}
        published = []
        for data in (unit_twin(1, "exp_unit"),
                     unit_twin(1, "exp_unit", randomizationType="unit",
                               **fields)):
            self.client.published.clear()
            self.clock.now = ANCHOR
            context = self.create_context([data])
            self.assertEqual(frozenset(), context._switchback_names)
            for i in range(3):
                self.clock.now = ANCHOR + i * HOUR
                context.get_treatment("exp_unit")
            published.append(self.serialized(self.publish_event(context)))
        self.assertEqual(published[0], published[1])

    def test_unknown_switchback_fields_are_ignored(self):
        context = self.create_context([switchback(
            switchbackClusterUnitType=UNIT_TYPE, switchbackClusterCount=10,
            switchbackClusterAttribute="city", futureSwitchback={"x": 1})])
        self.assertEqual(EXPECTED_2_ARMS[0], context.get_treatment("exp_sb"))


if __name__ == "__main__":
    unittest.main()
