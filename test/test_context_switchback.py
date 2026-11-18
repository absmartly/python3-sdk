"""Switchback serving through Context, ported from the Java SDK's
ContextSwitchbackTest (java-sdk main, core-api/src/test/java/com/absmartly/
sdk/ContextSwitchbackTest.java, merged in java-sdk#15). The rules are in the
Java SDK's SWITCHBACK.md.
"""
import json
import threading
import unittest

from sdk.audience_matcher import AudienceMatcher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.internal.variant_assigner import VariantAssigner
from sdk.utils import hash_unit
from test.holdout_fixtures import holdout
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

    def test_anchor_not_on_an_hour_boundary_is_unservable_on_get_and_post(self):
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

    def test_null_start_at_is_ineligible_and_never_falls_back_to_unit_assignment(self):
        context = self.create_context([switchback(switchbackStartAt=None)])
        for i in range(4):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(0, context.get_treatment("exp_sb"))
            # Variant 0's own config, like any ineligible assignment.
            self.assertEqual(0, context.get_variable_value("sb.arm", -1))
        self.assertEqual(0, context.get_pending_count())

    def test_same_period_is_cached_and_next_period_rolls_over_with_one_exposure_each(self):
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

    def test_variable_lookups_follow_the_period_and_expose_once_per_period(self):
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

        # Setting a linked unit later makes the experiment apply.
        context.set_unit(UNIT_TYPE, UID)
        self.assertEqual(EXPECTED_2_ARMS[2], context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", EXPECTED_2_ARMS[2], ANCHOR + 2 * HOUR))

    def test_overridden_absent_switchback_is_reresolved_once_its_unit_is_set(self):
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

    def test_refresh_invalidates_when_grid_fields_change_but_not_for_analysis_only_fields(self):
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

    def test_unservable_only_replaces_the_variant_draw_not_full_on_or_rules(self):
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

    def test_audience_strict_mismatch_with_an_unservable_schedule_is_recorded(self):
        self.clock.now = ANCHOR + HOUR + 3
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True,
            switchbackStartAt=None)])
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context,
                              strict_mismatch_exposure(ANCHOR + HOUR + 3))

    def test_audience_strict_mismatch_with_a_missing_or_unreadable_cluster_map_records_nothing(self):
        for cluster_map in (None, clusters(UNIT_TYPE, "'geo")):
            self.clock.now = ANCHOR + HOUR + 3
            context = self.create_context([switchback(
                audience=STRICT_GOLD_AUDIENCE, audienceStrict=True,
                switchbackClusters=cluster_map)])
            self.assertEqual(0, context.get_treatment("exp_sb"), cluster_map)
            self.assertEqual(0, context.get_pending_count(), cluster_map)

    def test_strict_mismatched_switchback_gives_way_on_a_shared_variable_key(self):
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

    def test_strict_mismatched_switchback_alone_on_a_variable_key_returns_the_default(self):
        self.clock.now = ANCHOR + HOUR + 3
        context = self.create_context([switchback(
            audience=STRICT_GOLD_AUDIENCE, audienceStrict=True)])
        self.assertEqual(-1, context.peek_variable_value("sb.arm", -1))
        self.assertEqual(-1, context.get_variable_value("sb.arm", -1))
        # Visited, so its strict-mismatch exposure is recorded (see above).
        self.assertEqual(1, context.get_pending_count())

    def test_traffic_miss_on_an_eligible_cluster_publishes_an_ineligible_exposure(self):
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
        # Unit experiments keep stamping at enqueue time, also in a payload
        # with switchbacks.
        context = self.create_context([switchback(randomizationType="unit"),
                                       switchback(2, "exp_other")])
        self.clock.now = ANCHOR + HOUR
        self.clock.next_read = ANCHOR + HOUR - 1
        variant = context.get_treatment("exp_sb")
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

        # An unchanged identity keeps the epoch.
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
        # Current again: no further evaluation.
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
        # At the anchor the draw can run, so the miss is recorded.
        self.clock.now = ANCHOR
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(1, "exp_sb", 0, ANCHOR,
                                                eligible=False))

    def test_override_without_a_serving_unit_on_a_legacy_switchback_uses_the_declared_unit_type(self):
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

    def test_queue_exposure_hook_sees_switchback_exposures_with_the_resolution_instant(self):
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
        # Holds both revalidating readers at a barrier, so both have found
        # the cached slot stale before either rebuilds it.
        def __init__(self):
            super().__init__(DefaultAudienceDeserializer())
            self.evaluations = 0
            self.lock = threading.Lock()
            self.readers = threading.Barrier(2, timeout=10)

        def evaluate(self, audience, attributes):
            with self.lock:
                self.evaluations += 1
                call = self.evaluations
            result = super().evaluate(audience, attributes)
            if 2 <= call <= 3:
                try:
                    self.readers.wait()
                except threading.BrokenBarrierError:
                    pass
            return result

    def test_concurrent_resolution_of_the_same_period_exposes_once(self):
        matcher = self.BarrierAudienceMatcher()
        context = self.create_context([switchback(audience=TRUE_AUDIENCE)],
                                      audience_matcher=matcher)
        self.clock.now = ANCHOR + HOUR + 10
        self.assertEqual(EXPECTED_2_ARMS[1], context.peek_treatment("exp_sb"))
        context.set_attribute("country", "PT")
        variants = [None, None]

        def read(i):
            variants[i] = context.get_treatment("exp_sb")

        workers = [threading.Thread(target=read, args=(i,), daemon=True)
                   for i in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertFalse(worker.is_alive())
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


class NoSwitchbackCostTest(SwitchbackTestCase):

    def test_a_payload_without_switchbacks_never_takes_the_switchback_path(self):
        context = self.create_context([unit_twin(1, "exp_unit")])
        self.assertFalse(context._has_switchbacks)
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
            self.assertFalse(context._has_switchbacks)
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
