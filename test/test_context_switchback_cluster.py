"""Cluster key selection through Context, ported from the Java SDK's
ContextSwitchbackClusterTest, ContextSwitchbackClusterRuleTest,
SwitchbackServerParityTest and SwitchbackServingTest (java-sdk main,
core-api/src/test/java/com/absmartly/sdk/). Variants come from the raw
cluster key and the switchback assigner, both pinned by the platform golden
vectors.
"""
import json
import math
import os
import unittest

from sdk.internal import switchback_serving
from sdk.internal.switchback_attribute_path import SwitchbackAttributePath
from sdk.internal.variant_assigner import VariantAssigner
from sdk.utils import hash_unit
from test.switchback_fixtures import (
    ANCHOR, HOUR, UID, UNIT_TYPE, SwitchbackFixture, clusters, draw,
    exposure, switchback, unit_twin)

ARMS = 3
RESOURCES = os.path.join(os.path.dirname(__file__), "res", "switchback")


def attribute_switchback(path, **fields):
    fields.setdefault("switchbackClusters", clusters(UNIT_TYPE, path))
    return switchback(arm_count=ARMS, **fields)


def expected(key, period):
    return draw(key, period, ARMS)


def expected_schedule(key):
    return [expected(key, i) for i in range(12)]


class ClusterTestCase(SwitchbackFixture, unittest.TestCase):
    def setUp(self):
        self.set_up_fixture()

    def context(self, experiments, units=None, attributes=None, **kwargs):
        return self.create_context(experiments, units=units,
                                   attributes=attributes,
                                   cluster_attribute=False, **kwargs)

    def resolution(self, context, name):
        experiment = context.get_experiment(name)
        period = experiment.switchback.period(self.clock.now)
        return context.assignment_cache.get(
            name if period is None else (name, period))


class ContextSwitchbackClusterTest(ClusterTestCase):

    def test_unit_uid_is_never_the_cluster_key(self):
        context = self.context([attribute_switchback("city")])
        for i in range(3):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())

    def test_numeric_unit_uid_clusters_like_its_canonical_string(self):
        for numeric, text in ((123456789, "123456789"),
                              (123456789.0, "123456789"),
                              (9007199254740993, "9007199254740992"),
                              (125.75, "126")):
            published = []
            schedules = []
            for uid in (numeric, text):
                self.client.published.clear()
                self.clock.now = ANCHOR
                context = self.context([attribute_switchback("city")],
                                       units={UNIT_TYPE: uid},
                                       attributes={"city": "Lisboa"})
                context.get_treatment("exp_sb")
                event = self.publish_event(context)
                published.append(([(u.type, u.uid) for u in event.units],
                                  [(e.unit, e.variant, e.exposedAt)
                                   for e in event.exposures]))
                schedules.append(self.peek_schedule(context, "exp_sb"))
            self.assertEqual(expected_schedule("Lisboa"), schedules[0])
            self.assertEqual(schedules[1], schedules[0])
            self.assertEqual(published[1], published[0])
            self.assertEqual(hash_unit(text), published[0][0][0][1])

    def test_numeric_unit_uid_matches_the_independent_reference(self):
        schedule = [0, 2, 1, 0, 1, 2, 0, 1, 2, 2, 1, 0]
        for uid, uid_hash in ((123456789, "JfnnlDI7RTiF9RgfG2JNCw"),
                              (9007199254740993, "OngwCmjeKhIQyeNybDy4eg")):
            self.client.published.clear()
            self.clock.now = ANCHOR
            context = self.context([attribute_switchback("region")],
                                   units={UNIT_TYPE: uid},
                                   attributes={"region": 123456789})
            context.get_treatment("exp_sb")
            event = self.publish_event(context)
            self.assertEqual(uid_hash, event.units[0].uid)
            self.assertEqual([exposure(1, "exp_sb", schedule[0], ANCHOR)],
                             [e for e in self.exposure_rows(event)])
            self.assertEqual(schedule, self.peek_schedule(context, "exp_sb"))

    @staticmethod
    def exposure_rows(event):
        return [(e.id, e.name, e.unit, e.variant, e.exposedAt, e.assigned,
                 e.eligible, e.overridden, e.fullOn, e.custom,
                 e.audienceMismatch, e.ruleOverride) for e in event.exposures]

    def test_attribute_source_serves_the_raw_attribute_value(self):
        context = self.context([attribute_switchback("city")],
                               attributes={"city": "Lisboa"})
        self.assertEqual([0, 2, 1, 2, 1, 0, 1, 0, 2, 0, 1, 2],
                         self.peek_schedule(context, "exp_sb"))
        self.assertEqual(expected_schedule("Lisboa"),
                         self.peek_schedule(context, "exp_sb"))

    def test_units_sharing_an_attribute_value_share_the_schedule(self):
        lisboa = self.context([attribute_switchback("city")],
                              attributes={"city": "Lisboa"})
        porto = self.context([attribute_switchback("city")],
                             attributes={"city": "Porto"})
        other_lisboa = self.context([attribute_switchback("city")],
                                    units={UNIT_TYPE: "another-store"},
                                    attributes={"city": "Lisboa"})
        self.assertEqual(expected_schedule("Lisboa"),
                         self.peek_schedule(lisboa, "exp_sb"))
        self.assertEqual(expected_schedule("Lisboa"),
                         self.peek_schedule(other_lisboa, "exp_sb"))
        self.assertEqual(expected_schedule("Porto"),
                         self.peek_schedule(porto, "exp_sb"))
        self.assertNotEqual(expected_schedule("Lisboa"),
                            expected_schedule("Porto"))

    def test_nested_and_array_paths_and_integer_values_resolve(self):
        import decimal
        import enum

        class Region(enum.IntEnum):
            NORTH = 42

        for path, attributes, key in (
                ("geo/city", {"geo": {"city": "Porto"}}, "Porto"),
                ("items/1/city", {"items": [{"city": "Lisbon"},
                                            {"city": "Faro"}]}, "Faro"),
                ("items/1/city", {"items": ({"city": "Lisbon"},
                                            {"city": "Faro"})}, "Faro"),
                ("region", {"region": 42}, "42"),
                # Values are read through their published JSON encoding,
                # which the Collector resolves the cluster from: a Decimal
                # publishes as text and an IntEnum as its name.
                ("geo/city", {"geo": {"city": decimal.Decimal("42")}}, "42"),
                ("region", {"region": Region.NORTH}, "NORTH"),
                ("geo/city", {"geo": {"city": Region.NORTH}}, "NORTH")):
            self.clock.now = ANCHOR
            context = self.context([attribute_switchback(path)],
                                   attributes=attributes)
            self.assertEqual(expected_schedule(key),
                             self.peek_schedule(context, "exp_sb"),
                             (path, attributes))

        self.clock.now = ANCHOR + 10
        floating = self.context([attribute_switchback("city")],
                                attributes={"city": 2.0})
        self.assertEqual(0, floating.get_treatment("exp_sb"))
        self.assertEqual(0, floating.get_pending_count())

    def test_values_without_a_cluster_key_are_ineligible(self):
        for value in (None, "", True, False, 1.5, 2.0, 3.0, -0.0, math.nan,
                      math.inf, {"a": "b"}, ["x"], (), b"42"):
            self.clock.now = ANCHOR
            context = self.context([attribute_switchback("city")],
                                   attributes={"city": value})
            self.clock.now = ANCHOR + 10
            self.assertEqual(0, context.get_treatment("exp_sb"), repr(value))
            # Variant 0's own config, like any ineligible assignment.
            self.assertEqual(0, context.get_variable_value("sb.arm", -1),
                             repr(value))
            self.assertEqual(0, context.get_pending_count(), repr(value))

        self.clock.now = ANCHOR
        missing = self.context([attribute_switchback("geo/city")],
                               attributes={"geo": {"country": "PT"}})
        self.clock.now = ANCHOR + 10
        self.assertEqual(0, missing.get_treatment("exp_sb"))
        self.assertEqual(0, missing.get_pending_count())

    def test_unencodable_attribute_values_are_ineligible(self):
        cyclic = {}
        cyclic["self"] = cyclic

        class Opaque:
            __slots__ = ()

        for value in (cyclic, Opaque(), {"city": {1, 2}}):
            context = self.context([attribute_switchback("geo/city")],
                                   attributes={"geo": value})
            self.assertEqual(0, context.get_treatment("exp_sb"))
            self.assertEqual(0, context.get_pending_count())

    def test_unservable_configurations_are_ineligible(self):
        experiments = [attribute_switchback(path) for path in (
            "items/0", "items/-1/city", "", "geo.city", "'city", '"city',
            None, 3)]
        experiments += [
            attribute_switchback("city", switchbackPeriodMs=None),
            attribute_switchback("city", switchbackPeriodMs=0),
            attribute_switchback("city", switchbackPeriodMs=-HOUR),
            attribute_switchback("city", split=[1.0]),
            attribute_switchback("city", switchbackClusters=["store_id"]),
            attribute_switchback("city", switchbackClusters="store_id"),
        ]
        for data in experiments:
            self.clock.now = ANCHOR
            context = self.context([data], attributes={
                "city": "Lisboa", "items": [{"city": "Lisbon"}]})
            for i in range(3):
                self.clock.now = ANCHOR + i * HOUR
                self.assertEqual(0, context.get_treatment("exp_sb"), data)
            self.assertEqual(0, context.get_pending_count(), data)

    def test_missing_or_empty_cluster_map_is_only_a_legacy_ineligible_control(self):
        for cluster_map in (None, {}):
            data = attribute_switchback("city",
                                        switchbackClusters=cluster_map)
            context = self.context([data], attributes={"city": "Lisboa"})
            self.assertEqual(0, context.get_treatment("exp_sb"))
            self.assertEqual(0, context.get_variable_value("sb.arm", -1))
            self.assertEqual(0, context.get_pending_count())

            other = self.context([data], units={"user_id": "u1"},
                                 attributes={"city": "Lisboa"})
            self.assertEqual(0, other.get_treatment("exp_sb"))
            self.assertEqual(-1, other.get_variable_value("sb.arm", -1))
            self.assertEqual(0, other.get_pending_count())

    def test_latest_attribute_set_at_or_before_the_resolution_instant_is_used(self):
        context = self.context([attribute_switchback("city")])
        self.clock.now = ANCHOR + 2 * HOUR
        context.set_attribute("city", "Porto")
        self.clock.now = ANCHOR + 4 * HOUR
        context.set_attribute("city", "Lisboa")

        self.clock.now = ANCHOR + HOUR
        self.assertEqual(0, context.peek_treatment("exp_sb"))
        self.clock.now = ANCHOR + 3 * HOUR
        self.assertEqual(expected("Porto", 3), context.peek_treatment("exp_sb"))
        self.clock.now = ANCHOR + 4 * HOUR
        self.assertEqual(expected("Lisboa", 4),
                         context.peek_treatment("exp_sb"))

    def test_set_attribute_mid_period_does_not_reassign_within_the_period(self):
        context = self.context([attribute_switchback("city")])
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "Lisboa")
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.clock.now = ANCHOR + 20
        context.set_attribute("city", "Porto")
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.assertEqual(expected("Lisboa", 0),
                         context.peek_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

        differing = 0
        for i in range(1, 12):
            self.clock.now = ANCHOR + i * HOUR
            self.assertEqual(expected("Porto", i),
                             context.get_treatment("exp_sb"))
            differing += expected("Porto", i) != expected("Lisboa", i)
        self.assertNotEqual(0, differing)
        self.assertEqual(12, context.get_pending_count())

    def test_attribute_set_after_an_ineligible_resolution_waits_for_the_next_period(self):
        context = self.context([attribute_switchback("city")])
        self.clock.now = ANCHOR + 10
        self.assertEqual(0, context.get_treatment("exp_sb"))
        context.set_attribute("city", "Lisboa")
        self.clock.now = ANCHOR + 20
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())

        self.clock.now = ANCHOR + HOUR
        self.assertEqual(expected("Lisboa", 1),
                         context.get_treatment("exp_sb"))
        self.assert_published(context, exposure(
            1, "exp_sb", expected("Lisboa", 1), ANCHOR + HOUR))

    def test_traffic_changes_within_the_period_keep_the_periods_bucket(self):
        context = self.context([attribute_switchback("city")])
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "Lisboa")
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))

        self.clock.now = ANCHOR + 20
        context.set_attribute("city", "Porto")
        self.refresh_to(context, attribute_switchback(
            "city", trafficSplit=[1.0, 0.0]))
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.refresh_to(context, attribute_switchback("city"))
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

        self.clock.now = ANCHOR + HOUR
        self.assertEqual(expected("Porto", 1), context.get_treatment("exp_sb"))

    def test_traffic_restored_within_the_period_keeps_the_key(self):
        context = self.context([attribute_switchback(
            "city", trafficSplit=[1.0, 0.0])])
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "Faro")
        self.assertEqual(0, context.get_treatment("exp_sb"))

        self.clock.now = ANCHOR + 20
        context.set_attribute("city", "Lisboa")
        self.refresh_to(context, attribute_switchback("city"))
        self.assertEqual(1, expected("Faro", 0))
        self.assertEqual(expected("Faro", 0), context.get_treatment("exp_sb"))
        self.assert_published(
            context, exposure(1, "exp_sb", 0, ANCHOR + 10, eligible=False),
            exposure(1, "exp_sb", expected("Faro", 0), ANCHOR + 20))

    def test_audience_revalidation_after_set_attribute_keeps_the_periods_bucket(self):
        audience = json.dumps(
            {"filter": [{"eq": [{"var": "tier"}, {"value": "gold"}]}]})
        context = self.context([attribute_switchback("city",
                                                     audience=audience)])
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "Lisboa")
        context.set_attribute("tier", "gold")
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))

        self.clock.now = ANCHOR + 20
        context.set_attribute("city", "Porto")
        context.set_attribute("tier", "silver")
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.assert_published(
            context, exposure(1, "exp_sb", expected("Lisboa", 0), ANCHOR + 10),
            exposure(1, "exp_sb", expected("Lisboa", 0), ANCHOR + 20,
                     audience_mismatch=True))

    def test_unchanged_audience_after_set_attribute_keeps_the_exposed_slot(self):
        audience = json.dumps(
            {"filter": [{"eq": [{"var": "tier"}, {"value": "gold"}]}]})
        context = self.context([attribute_switchback("city",
                                                     audience=audience)],
                               attributes={"city": "Lisboa", "tier": "gold"})
        self.clock.now = ANCHOR + 10
        first = context.get_treatment("exp_sb")
        context.set_attribute("other", "x")
        self.assertEqual(first, context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

    def test_audience_revalidation_after_an_ineligible_resolution_keeps_the_missing_key(self):
        audience = json.dumps(
            {"filter": [{"eq": [{"var": "tier"}, {"value": "gold"}]}]})
        context = self.context([attribute_switchback("city",
                                                     audience=audience)])
        self.clock.now = ANCHOR + 10
        context.set_attribute("tier", "gold")
        self.assertEqual(0, context.get_treatment("exp_sb"))

        self.clock.now = ANCHOR + 20
        context.set_attribute("city", "Faro")
        context.set_attribute("tier", "silver")
        self.assertEqual(1, expected("Faro", 0))
        self.assertEqual(0, context.get_treatment("exp_sb"))
        self.assertEqual(0, context.get_pending_count())

        self.clock.now = ANCHOR + HOUR
        self.assertEqual(expected("Faro", 1), context.peek_treatment("exp_sb"))
        # Period 1 of Faro is variant 0; period 2 is not, so the key is
        # visibly read again.
        self.clock.now = ANCHOR + 2 * HOUR
        self.assertEqual(2, expected("Faro", 2))
        self.assertEqual(expected("Faro", 2), context.peek_treatment("exp_sb"))

    def test_cluster_path_changes_invalidate_the_period(self):
        context = self.context([attribute_switchback("city")])
        self.clock.now = ANCHOR + 10
        context.set_attribute("city", "Lisboa")
        context.set_attribute("geo", {"city": "Porto"})
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

        self.refresh_to(context, attribute_switchback("city"))
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.assertEqual(1, context.get_pending_count())

        self.refresh_to(context, attribute_switchback("geo/city"))
        self.assertEqual(expected("Porto", 0), context.get_treatment("exp_sb"))
        self.assertEqual(2, context.get_pending_count())

        self.refresh_to(context, attribute_switchback(
            "geo/city", switchbackClusterValues=["Porto", "Faro"]))
        self.assertEqual(expected("Porto", 0), context.get_treatment("exp_sb"))
        self.assertEqual(3, context.get_pending_count())

    def test_linked_unit_type_change_rekeys_the_period(self):
        context = self.context([attribute_switchback("city")],
                               units={UNIT_TYPE: UID, "user_id": "user-0002"})
        self.clock.now = ANCHOR + 1
        context.set_attribute("city", "Lisboa")
        context.set_attribute("ucity", "Faro")
        self.assertEqual(expected("Lisboa", 0),
                         context.get_treatment("exp_sb"))
        self.refresh_to(context, attribute_switchback(
            "ucity", switchbackClusters=clusters("user_id", "ucity")))
        self.assertEqual(expected("Faro", 0), context.get_treatment("exp_sb"))
        self.assertEqual([UNIT_TYPE, "user_id"],
                         [e[2] for e in self.published_exposures(context)])

    def test_custom_assignment_applies_only_to_units_with_a_cluster_key(self):
        keyed = self.context([attribute_switchback("city")],
                             attributes={"city": "Lisboa"})
        keyed.set_custom_assignment("exp_sb", 2)
        self.assertEqual(2, keyed.get_treatment("exp_sb"))
        unkeyed = self.context([attribute_switchback("city")])
        unkeyed.set_custom_assignment("exp_sb", 2)
        self.assertEqual(0, unkeyed.get_treatment("exp_sb"))

    def test_unit_experiments_ignore_cluster_fields(self):
        split_rule = json.dumps({"rules": [{
            "type": "split", "environments": [],
            "percentages": "34/33/33"}]})
        for randomization_type in ("unit", None):
            published = []
            unit = attribute_switchback(
                "city", randomizationType=randomization_type,
                switchbackClusters=clusters("user_id", "city", UNIT_TYPE,
                                            "'x"),
                switchbackClusterValues=["nothing"], switchbackPeriodMs=0,
                assignmentRules=split_rule)
            reference = unit_twin(1, "exp_sb", ARMS,
                                  assignmentRules=split_rule)
            for data in (unit, reference):
                self.client.published.clear()
                self.clock.now = ANCHOR - HOUR
                context = self.context([data],
                                       units={UNIT_TYPE: UID, "user_id": "u"},
                                       attributes={"city": "Lisboa"})
                first = context.get_treatment("exp_sb")
                for i in range(1, 6):
                    self.clock.now = ANCHOR - HOUR + i * HOUR
                    self.assertEqual(first, context.get_treatment("exp_sb"))
                published.append(self.published_exposures(context))
            self.assertEqual(1, len(published[0]))
            self.assertTrue(published[0][0][6])
            self.assertTrue(published[0][0][11])
            self.assertEqual(ANCHOR - HOUR, published[0][0][4])
            self.assertEqual(published[1], published[0])


SESSION = "session_id"
USER = "user_id"
RULE_ANCHOR = ANCHOR
PERIOD = 5
NOW = RULE_ANCHOR + PERIOD * HOUR + 17 * 60_000
RULE_SEED_HI = 0x1234
RULE_SEED_LO = 0x5678abcd
RULE_SEED = (RULE_SEED_HI << 32) | (RULE_SEED_LO & 0xffffffff)


def sbc(**fields):
    # The Collector's ClusterRule fixture: "sbc" (id 900, "34/33/33", 1h)
    # linked to session_id (unit type id 1) at "session_store" and user_id
    # (unit type id 2) at "profile/store", in unit type id order.
    data = switchback(900, "sbc", 3, seedHi=RULE_SEED_HI, seedLo=RULE_SEED_LO,
                      unitType=USER, split=[0.34, 0.33, 0.33],
                      trafficSeedHi=7, trafficSeedLo=11,
                      switchbackClusters=clusters(SESSION, "session_store",
                                                  USER, "profile/store"),
                      switchbackCarryoverDurationMs=None,
                      switchbackBurnInDurationMs=None,
                      switchbackBurnOutDurationMs=None,
                      switchbackEstimand=None)
    data["variants"] = [{"name": str(i),
                         "config": json.dumps({"sbc.config":
                                               f"test config {i}"})}
                        for i in range(3)]
    data.update(fields)
    return data


def scheduled(key):
    return draw(key, PERIOD, 3, RULE_SEED)


class ContextSwitchbackClusterRuleTest(ClusterTestCase):
    """Port of the Collector's ContextAPISwitchbackTest ClusterRule section.
    A context holds one uid per unit type, so the declared source order
    alone decides which unit serves."""

    def setUp(self):
        super().setUp()
        self.clock.now = NOW

    def serve(self, attributes, units, experiments=None):
        """{unit, eligible, silent, variant, config, exposures} for sbc,
        or None when the Collector lists no assignment."""
        experiments = experiments or [sbc()]
        self.logger.events.clear()
        context = self.context(experiments, units=units,
                               attributes=attributes)
        for data in experiments:
            if data["name"] != "sbc":
                context.get_treatment(data["name"])
        variant = context.get_treatment("sbc")
        resolution = self.resolution(context, "sbc")
        self.assertIsNotNone(resolution)
        config = context.get_variable_value("sbc.config", None)
        exposures = [e for e in self.logged_exposures() if e.name == "sbc"]
        if resolution.switchback_serving.status == switchback_serving.ABSENT:
            self.assertEqual(0, variant)
            self.assertIsNone(config)
            self.assertEqual([], exposures)
            return None
        return {"unit": resolution.unit_type,
                "eligible": resolution.eligible,
                "silent": resolution.switchback_silent,
                "variant": variant, "full_on": resolution.full_on,
                "rule_override": resolution.rule_override,
                "config": config, "exposures": exposures}

    def assert_ineligible(self, attributes, expected_unit, units,
                          experiments=None):
        assignment = self.serve(attributes, units, experiments)
        self.assertIsNotNone(assignment, attributes)
        self.assertEqual(expected_unit, assignment["unit"])
        self.assertFalse(assignment["eligible"])
        self.assertTrue(assignment["silent"])
        self.assertEqual(0, assignment["variant"])
        self.assertFalse(assignment["full_on"])
        self.assertFalse(assignment["rule_override"])
        self.assertEqual("test config 0", assignment["config"])
        self.assertEqual([], assignment["exposures"], attributes)

    def test_missing_or_unreadable_cluster_configuration_returns_only_legacy_ineligible_control(self):
        attributes = {"geo": {"city": "Porto"}, "geo.city": "Faro",
                      "session_store": "s-1"}
        for broken in (None, {}, clusters(SESSION, "'geo"),
                       clusters(SESSION, "geo.city"),
                       clusters(SESSION, "'geo.city'"),
                       clusters(SESSION, '"geo.city"')):
            experiments = [sbc(switchbackClusters=broken)]
            # The declared unit (user_id) only identifies an ineligible
            # control response.
            self.assert_ineligible(attributes, USER,
                                   {SESSION: "x1", USER: "u1"}, experiments)
            # Without a unit of the declared type there is no response.
            self.assertIsNone(self.serve(attributes, {SESSION: "x1"},
                                         experiments), broken)
        # A readable map whose only linked type is absent from the context.
        self.assertIsNone(self.serve(
            {"session_store": "s-1"}, {SESSION: "x1", USER: "u1"},
            [sbc(switchbackClusters=clusters("device_id", "session_store"))]))

    def test_traffic_uses_serving_uid_not_experiment_uid(self):
        split = [0.6, 0.4]
        witnesses = [None, None]
        for i in range(1000):
            uid = f"traffic-{i}"
            arm = VariantAssigner(bytearray(hash_unit(uid).encode())) \
                .assign(split, 7, 11)
            witnesses[0 if arm == 0 else 1] = witnesses[
                0 if arm == 0 else 1] or uid
            if all(witnesses):
                break
        key = "s-18"
        self.assertNotEqual(0, scheduled(key))
        ordinary = unit_twin(901, "ordinary", unitType=USER,
                             trafficSeedHi=7, trafficSeedLo=11,
                             trafficSplit=[0.0, 1.0])
        for serving_eligible in (False, True):
            assignment = self.serve(
                {"session_store": key, "profile": {"store": key}},
                {SESSION: witnesses[1 if serving_eligible else 0],
                 USER: witnesses[0 if serving_eligible else 1]},
                [sbc(trafficSplit=split), ordinary])
            self.assertEqual(SESSION, assignment["unit"])
            self.assertEqual(serving_eligible, assignment["eligible"])
            self.assertEqual(scheduled(key) if serving_eligible else 0,
                             assignment["variant"])
            # A traffic miss on an eligible cluster is still recorded.
            self.assertEqual(1, len(assignment["exposures"]))
            self.assertEqual(SESSION, assignment["exposures"][0].unit)
            self.assertEqual(serving_eligible,
                             assignment["exposures"][0].eligible)

    def test_one_matching_unit_serves_its_value(self):
        assignment = self.serve({"profile": {"store": "s-17"}}, {USER: "u1"})
        self.assertTrue(assignment["eligible"])
        self.assertEqual(USER, assignment["unit"])
        self.assertEqual(scheduled("s-17"), assignment["variant"])

    def test_strict_audience_mismatch_on_an_eligible_cluster_is_listed_as_control_and_recorded(self):
        audience = json.dumps(
            {"filter": [{"eq": [{"var": "tier"}, {"value": "gold"}]}]})
        assignment = self.serve({"session_store": "s-17"}, {SESSION: "x1"},
                                [sbc(audience=audience, audienceStrict=True)])
        self.assertEqual(SESSION, assignment["unit"])
        self.assertTrue(assignment["eligible"])
        self.assertFalse(assignment["silent"])
        self.assertEqual(0, assignment["variant"])
        self.assertEqual(1, len(assignment["exposures"]))
        self.assertTrue(assignment["exposures"][0].audienceMismatch)
        self.assertFalse(assignment["exposures"][0].assigned)

    def test_two_agreeing_units_serve_the_value(self):
        assignment = self.serve(
            {"profile": {"store": "s-17"}, "session_store": "s-17"},
            {USER: "u1", SESSION: "x1"})
        self.assertTrue(assignment["eligible"])
        self.assertEqual(scheduled("s-17"), assignment["variant"])

    def test_two_disagreeing_units_are_ineligible(self):
        # session_id is first in declared order whatever the unit order.
        self.assert_ineligible(
            {"profile": {"store": "s-17"}, "session_store": "s-18"}, SESSION,
            {USER: "u1", SESSION: "x1"})

    def test_a_second_uid_of_one_type_is_rejected(self):
        context = self.context([sbc()], units={SESSION: "x1"},
                               attributes={"session_store": "s-17"})
        with self.assertRaises(ValueError):
            context.set_unit(SESSION, "x2")
        self.assertEqual(scheduled("s-17"), context.get_treatment("sbc"))

    def test_no_matching_unit_is_not_applicable(self):
        self.assertIsNone(self.serve({"session_store": "s-1"},
                                     {"device_id": "d1"}))
        self.assertIsNone(self.serve({"session_store": "s-1"}, {}))

    def test_ineligible_cluster_is_listed_under_the_first_linked_unit(self):
        # The first linked unit has no value and the later ones disagree, or
        # the only value is filtered out: the control is listed under the
        # first linked unit, not the first unit with a value.
        three = clusters(SESSION, "session_store", USER, "profile/store",
                         "device_id", "device_store")
        units = {SESSION: "x1", USER: "u1", "device_id": "d1"}
        self.assert_ineligible(
            {"profile": {"store": "s-1"}, "device_store": "s-2"}, SESSION,
            units, [sbc(switchbackClusters=three)])
        self.assert_ineligible(
            {"profile": {"store": "s-1"}}, SESSION, units,
            [sbc(switchbackClusters=three, switchbackClusterValues=["s-9"])])

    def test_matching_unit_without_a_value_is_ineligible(self):
        self.assert_ineligible({"other": "s-1"}, USER, {USER: "u1"})
        self.assert_ineligible({"other": "s-1"}, SESSION,
                               {USER: "u1", SESSION: "x1"})

    def test_non_string_non_integer_values_are_ineligible(self):
        for value in (1.5, 3.0, True, False, {"a": 1}, ["a"], ""):
            self.assert_ineligible({"session_store": value}, SESSION,
                                   {SESSION: "x1"})

    def test_whole_numbers_are_keyed_by_their_decimal_text(self):
        self.assertNotEqual(0, scheduled("17"))
        assignment = self.serve({"session_store": 17}, {SESSION: "x1"})
        self.assertTrue(assignment["eligible"])
        self.assertEqual(scheduled("17"), assignment["variant"])
        # Equal to the string "17" from another unit type: they agree.
        self.assertTrue(self.serve(
            {"session_store": 17, "profile": {"store": "17"}},
            {SESSION: "x1", USER: "u1"})["eligible"])

    def test_nested_and_array_paths_are_read(self):
        assignment = self.serve(
            {"items": [{"store": "a"}, {"store": "b"}]}, {SESSION: "x1"},
            [sbc(switchbackClusters=clusters(SESSION, "items/1/store"))])
        self.assertEqual(scheduled("b"), assignment["variant"])
        self.assertNotEqual(scheduled("a"), scheduled("b"))

    def test_exposure_unit_is_the_first_matching_unit_in_declared_order(self):
        key = "s-18"
        self.assertNotEqual(0, scheduled(key))
        assignment = self.serve(
            {"profile": {"store": key}, "session_store": key},
            {USER: "u1", SESSION: "x1"})
        self.assertEqual(SESSION, assignment["unit"])
        self.assertEqual(SESSION, assignment["exposures"][0].unit)
        self.assertEqual(scheduled(key), assignment["variant"])

    def test_ineligible_cluster_never_publishes_an_exposure(self):
        context = self.context([sbc()], units={USER: "u1", SESSION: "x1"},
                               attributes={"session_store": "a",
                                           "profile": {"store": "b"}})
        self.assertEqual(0, context.get_treatment("sbc"))
        self.assertEqual(0, context.get_pending_count())
        context.publish()
        self.assertEqual([], self.client.published)
        self.assertEqual([], self.logged_exposures())

    def test_a_unit_without_a_value_does_not_serve_even_if_first_in_declared_order(self):
        key = "s-17"
        self.assertNotEqual(0, scheduled(key))
        assignment = self.serve({"profile": {"store": key}},
                                {SESSION: "x1", USER: "u1"})
        self.assertEqual(USER, assignment["unit"])
        self.assertEqual(USER, assignment["exposures"][0].unit)
        self.assertEqual(scheduled(key), assignment["variant"])

    def test_value_not_in_the_filter_is_ineligible(self):
        experiments = [sbc(switchbackClusterValues=["s-1", "s-2"])]
        self.assert_ineligible({"session_store": "s-3"}, SESSION,
                               {SESSION: "x1"}, experiments)
        allowed = self.serve({"session_store": "s-2"}, {SESSION: "x1"},
                             experiments)
        self.assertTrue(allowed["eligible"])
        self.assertEqual(scheduled("s-2"), allowed["variant"])

    def test_malformed_allow_lists(self):
        # Non-string entries never equal a key; a list of only those filters
        # every value out. A non-list value is no allow-list.
        for values, eligible in (([17], False), ([17, "17"], True),
                                 ([None], False), ("17", True),
                                 ({"17": 1}, True)):
            assignment = self.serve(
                {"session_store": 17}, {SESSION: "x1"},
                [sbc(switchbackClusterValues=values)])
            self.assertEqual(eligible, assignment["eligible"], values)

    def test_null_or_empty_filter_assigns_every_value(self):
        for values in (None, []):
            for i in range(20):
                assignment = self.serve(
                    {"session_store": f"s-{i}"}, {SESSION: "x1"},
                    [sbc(switchbackClusterValues=values)])
                self.assertTrue(assignment["eligible"])
                self.assertEqual(scheduled(f"s-{i}"), assignment["variant"])

    def test_valid_cluster_without_linked_unit_does_not_fall_back_to_experiment_unit(self):
        experiments = [sbc(switchbackClusters=clusters(SESSION,
                                                       "session_store"))]
        key = "s-17"
        self.assertNotEqual(0, scheduled(key))
        self.assertIsNone(self.serve(
            {"session_store": key, "profile": {"store": key}}, {USER: "u1"},
            experiments))
        linked = self.serve({"session_store": key},
                            {USER: "u1", SESSION: "x1"}, experiments)
        self.assertEqual(SESSION, linked["unit"])
        self.assertEqual(scheduled(key), linked["variant"])

    def test_context_matches_the_sdk_switchback_wire_rule_parity_grid(self):
        # The Collector's SdkSwitchbackRule oracle, transcribed: period from
        # the anchor, traffic on the serving uid's hash, then the draw over
        # the cluster key; no key (no value, disagreement, filtered) has no
        # draw.
        def oracle(data, uid, key, now):
            start, period_ms = data["switchbackStartAt"], \
                data["switchbackPeriodMs"]
            if key is None or now < start:
                return 0, False
            eligible = VariantAssigner(bytearray(hash_unit(uid).encode())) \
                .assign(data["trafficSplit"], 7, 11) == 1
            if not eligible:
                return 0, False
            return draw(key, (now - start) // period_ms, 3, RULE_SEED), True

        counts = {"eligible": 0, "ineligible": 0, "traffic_misses": 0}
        for case in ("single", "disagreeing", "missing", "filtered"):
            for anchor in (RULE_ANCHOR, RULE_ANCHOR + 7 * HOUR):
                for period_ms in (HOUR, 2 * HOUR, 24 * HOUR):
                    for u in range(3):
                        uid = f"uid-{u}"
                        for key in ("s-1", "42", "Lisboa"):
                            for now in (anchor - 1, anchor,
                                        anchor + period_ms - 1,
                                        anchor + period_ms,
                                        anchor + 11 * period_ms):
                                self.check_grid_case(
                                    case, anchor, period_ms, uid, key, now,
                                    oracle, counts)
        self.assertGreater(counts["eligible"], 50)
        self.assertGreater(counts["ineligible"], 50)
        self.assertGreater(counts["traffic_misses"], 0)

    def check_grid_case(self, case, anchor, period_ms, uid, key, now, oracle,
                        counts):
        fields = {"trafficSplit": [0.3, 0.7], "switchbackStartAt": anchor,
                  "switchbackPeriodMs": period_ms,
                  "switchbackClusters": clusters(SESSION, "session_store")}
        attributes = {"session_store": key}
        units = {SESSION: uid}
        if case == "disagreeing":
            fields["switchbackClusters"] = clusters(
                SESSION, "session_store", USER, "profile/store")
            attributes["profile"] = {"store": key + "-other"}
            units[USER] = "u-" + uid
        elif case == "missing":
            attributes = {"other": key}
        elif case == "filtered":
            fields["switchbackClusterValues"] = [key + "-allowed"]
        data = sbc(**fields)
        self.clock.now = now
        self.logger.events.clear()
        context = self.context([data], units=units, attributes=attributes)
        oracle_key = key if case == "single" else None
        variant, eligible = oracle(data, uid, oracle_key, now)
        message = (case, anchor, period_ms, uid, key, now)
        self.assertEqual(variant, context.get_treatment("sbc"), message)
        self.assertEqual(eligible, self.resolution(context, "sbc").eligible,
                         message)
        exposures = self.logged_exposures()
        expected_exposures = 1 if oracle_key is not None and now >= anchor \
            else 0
        self.assertEqual(expected_exposures, len(exposures), message)
        if expected_exposures:
            self.assertEqual(eligible, exposures[0].eligible, message)
        if case == "single":
            if eligible:
                counts["eligible"] += 1
            else:
                counts["ineligible"] += 1
                if now >= anchor:
                    counts["traffic_misses"] += 1


PARITY_SEED = 1_234_567_890_123
STORE = "store_id"
DEVICE = "device_id"
TWO_SOURCES = clusters(STORE, "store_city", DEVICE, "geo/city")


def parity_experiment(cluster_map, values=None, **fields):
    data = switchback(1, "exp_sb", ARMS, unitType=USER,
                      seedHi=PARITY_SEED >> 32,
                      seedLo=PARITY_SEED & 0xffffffff,
                      switchbackClusters=cluster_map,
                      switchbackClusterValues=values)
    data["variants"] = [{"name": str(i), "config": None} for i in range(ARMS)]
    data.update(fields)
    return data


class SwitchbackServerParityTest(ClusterTestCase):
    """Replays the Collector's R33 serving rules through Context; each case
    states the serving unit type and the raw cluster key the Collector
    picks, or that it records nothing."""

    PERIODS = 4

    def serve(self, data, units, attributes):
        self.logger.events.clear()
        self.clock.now = ANCHOR
        context = self.context([data], units=units, attributes=attributes)
        variants = []
        for p in range(self.PERIODS):
            self.clock.now = ANCHOR + p * HOUR + 1
            variants.append(context.get_treatment("exp_sb"))
        return variants, self.logged_exposures()

    def assert_eligible(self, served, serving_type, key, message):
        variants, exposures = served
        self.assertEqual(self.PERIODS, len(exposures), message)
        for p in range(self.PERIODS):
            want = draw(key, p, ARMS, PARITY_SEED)
            self.assertEqual(want, variants[p], (message, p))
            self.assertEqual(serving_type, exposures[p].unit, message)
            self.assertEqual(want, exposures[p].variant, message)
            self.assertTrue(exposures[p].assigned, message)
            self.assertTrue(exposures[p].eligible, message)
            self.assertEqual(ANCHOR + p * HOUR + 1, exposures[p].exposedAt,
                             message)

    def assert_silent_control(self, served, message):
        variants, exposures = served
        self.assertEqual([0] * self.PERIODS, variants, message)
        self.assertEqual([], exposures, message)

    @staticmethod
    def two_units():
        return {STORE: "s1", DEVICE: "d1"}

    def test_raw_key_schedules_match_the_independent_reference(self):
        self.assert_eligible(self.serve(
            parity_experiment(clusters(STORE, "city")), {STORE: "s1"},
            {"city": "Lisboa"}), STORE, "Lisboa", "Lisboa")
        self.assertEqual([0, 1, 2, 2], [draw("Lisboa", p, ARMS, PARITY_SEED)
                                        for p in range(4)])
        self.assertEqual([2, 1, 0, 1], [draw("Porto", p, ARMS, PARITY_SEED)
                                        for p in range(4)])
        self.assertEqual([0, 2, 1, 2], [draw("42", p, ARMS, PARITY_SEED)
                                        for p in range(4)])

    def test_agreement_serves_the_first_source_unit(self):
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(),
            {"store_city": "Lisboa", "geo": {"city": "Lisboa"}}),
            STORE, "Lisboa", "agreement")

    def test_disagreement_is_ineligible_and_records_nothing(self):
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(),
            {"store_city": "Lisboa", "geo": {"city": "Porto"}}),
            "disagreement")

    def test_missing_value_is_skipped_and_the_next_value_serves(self):
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(),
            {"geo": {"city": "Porto"}}), DEVICE, "Porto",
            "first source missing")
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(),
            {"store_city": "Porto"}), STORE, "Porto", "second source missing")
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(), {"other": "x"}),
            "no value at all")
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(), None),
            "no attributes")

    def test_only_linked_units_present_in_the_context_take_part(self):
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), {DEVICE: "d1"},
            {"store_city": "Lisboa", "geo": {"city": "Porto"}}),
            DEVICE, "Porto", "store unit absent")

    def test_filtered_value_is_ineligible_and_allowed_value_serves(self):
        lisboa = {"store_city": "Lisboa"}
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES, ["Porto", "Faro"]),
            self.two_units(), lisboa), "filtered")
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES, ["Porto", "Lisboa"]),
            self.two_units(), lisboa), STORE, "Lisboa", "allowed")
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES, None), self.two_units(), lisboa),
            STORE, "Lisboa", "null filter")
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES, []), self.two_units(), lisboa),
            STORE, "Lisboa", "empty filter")
        # The filter compares the normalised text of numeric values.
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES, ["42"]), self.two_units(),
            {"store_city": 42}), STORE, "42", "numeric filter")
        # A filtered first value is not replaced by a later allowed one.
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES, ["Porto"]), self.two_units(),
            {"store_city": "Lisboa", "geo": {"city": "Porto"}}),
            "filtered first value")

    def test_lower_unit_type_id_source_serves_first(self):
        # The declared order decides, not the order units were set in.
        agreeing = {"store_city": "Lisboa", "geo": {"city": "Lisboa"}}
        units = {STORE: "s1", DEVICE: "d1"}
        device_first = clusters(DEVICE, "geo/city", STORE, "store_city")
        self.assert_eligible(self.serve(
            parity_experiment(device_first), units, agreeing),
            DEVICE, "Lisboa", "device declared first")
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), units, agreeing),
            STORE, "Lisboa", "store declared first")
        reversed_units = {DEVICE: "d1", STORE: "s1"}
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), reversed_units, agreeing),
            STORE, "Lisboa", "units set device first")

    def test_many_sources_keep_the_declared_non_alphabetical_order(self):
        # Decoded from JSON whose key order is not alphabetical; a sorted
        # map would serve "a_unit" first.
        payload = ('{"z_unit": "z", "m_unit": "m", "a_unit": "a"}')
        cluster_map = json.loads(payload)
        self.assertEqual(["z_unit", "m_unit", "a_unit"], list(cluster_map))
        units = {"a_unit": "1", "m_unit": "2", "z_unit": "3"}
        for attributes, serving, key in (
                ({"z": "Z", "m": "M", "a": "A"}, None, None),
                ({"m": "K", "a": "K"}, "m_unit", "K"),
                ({"z": "K", "m": "K", "a": "K"}, "z_unit", "K")):
            served = self.serve(parity_experiment(cluster_map), units,
                                attributes)
            if serving is None:
                self.assert_silent_control(served, attributes)
            else:
                self.assert_eligible(served, serving, key, attributes)

    def test_non_key_values_are_ignored(self):
        for value in (True, False, 1.5, 2.0, {"a": "b"}, ["x"], [], None, ""):
            message = f"ignored {value!r}"
            self.assert_eligible(self.serve(
                parity_experiment(TWO_SOURCES), self.two_units(),
                {"store_city": value, "geo": {"city": "Porto"}}),
                DEVICE, "Porto", message)
            self.assert_silent_control(self.serve(
                parity_experiment(clusters(STORE, "store_city")),
                {STORE: "s1"}, {"store_city": value}), message + " alone")

    def test_numeric_values_are_keyed_as_text(self):
        for store in (42, "42"):
            for device in (42, "42"):
                self.assert_eligible(self.serve(
                    parity_experiment(TWO_SOURCES), self.two_units(),
                    {"store_city": store, "geo": {"city": device}}),
                    STORE, "42", f"{store!r}/{device!r}")
        self.assert_eligible(self.serve(
            parity_experiment(clusters(STORE, "n")), {STORE: "s1"},
            {"n": 123456789012345678901234567890}), STORE,
            "123456789012345678901234567890", "big integer")
        self.assert_eligible(self.serve(
            parity_experiment(clusters(STORE, "n")), {STORE: "s1"}, {"n": -7}),
            STORE, "-7", "negative")
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(),
            {"store_city": 42, "geo": {"city": "042"}}), "42 vs 042")
        # 42.0 is a float, which gives no value: skipped, not a
        # disagreement.
        self.assert_eligible(self.serve(
            parity_experiment(TWO_SOURCES), self.two_units(),
            {"store_city": 42, "geo": {"city": 42.0}}), STORE, "42",
            "42 and 42.0")
        self.assert_silent_control(self.serve(
            parity_experiment(clusters(STORE, "n")), {STORE: "s1"},
            {"n": 42.0}), "42.0 alone")

    def test_malformed_paths_are_unservable(self):
        attributes = {"store_city": "Lisboa", "geo": {"city": "Porto"},
                      "geo.city": "Faro"}
        for path in ("'geo/city", '"geo', "geo/'city", "geo.city", "geo/a.b",
                     "'geo.city'", '"geo.city"'):
            self.assert_silent_control(self.serve(
                parity_experiment(clusters(STORE, "store_city", DEVICE, path)),
                self.two_units(), attributes), path)
            self.assert_silent_control(self.serve(
                parity_experiment(clusters(DEVICE, path)), self.two_units(),
                attributes), path + " alone")

    def test_no_linked_unit_is_absent(self):
        self.assert_silent_control(self.serve(
            parity_experiment(TWO_SOURCES), {USER: "u1"},
            {"store_city": "Lisboa"}), "no linked unit")

    def test_traffic_follows_the_serving_unit_hash(self):
        eligible = ineligible = 0
        for u in range(24):
            sb = parity_experiment(TWO_SOURCES, trafficSplit=[0.5, 0.5],
                                   trafficSeedHi=3, trafficSeedLo=4)
            twin = unit_twin(2, "exp_unit", ARMS, unitType=DEVICE,
                             trafficSplit=[0.5, 0.5], trafficSeedHi=3,
                             trafficSeedLo=4)
            self.logger.events.clear()
            self.clock.now = ANCHOR
            context = self.context([sb, twin],
                                   units={STORE: "s1", DEVICE: f"device-{u}"},
                                   attributes={"geo": {"city": "Porto"}})
            context.get_treatment("exp_unit")
            twin_eligible = self.logged_exposures()[0].eligible
            for p in range(self.PERIODS):
                self.clock.now = ANCHOR + p * HOUR
                variant = context.get_treatment("exp_sb")
                exposure_ = self.logged_exposures()[p + 1]
                self.assertEqual(DEVICE, exposure_.unit)
                self.assertEqual(twin_eligible, exposure_.eligible)
                self.assertEqual(draw("Porto", p, ARMS, PARITY_SEED)
                                 if twin_eligible else 0, variant)
            if twin_eligible:
                eligible += 1
            else:
                ineligible += 1
        self.assertGreater(eligible, 0)
        self.assertGreater(ineligible, 0)

    def test_attribute_path_cases_match_the_collector(self):
        with open(os.path.join(RESOURCES, "attribute-path-cases.json")) as f:
            fixture = json.load(f)
        eligible_cases = 0
        for c in fixture["cases"]:
            served = self.serve(parity_experiment(clusters(STORE, c["path"])),
                                {STORE: "s1"}, fixture["attributes"])
            if not c["supported"] or c["value"] is None:
                self.assert_silent_control(served, c)
                continue
            self.assert_eligible(served, STORE, c["value"], c)
            eligible_cases += 1
        self.assertEqual(3, eligible_cases)

    def test_repeated_attribute_names_resolve_to_the_latest(self):
        self.assert_eligible(self.serve(
            parity_experiment(clusters(STORE, "cluster")), {STORE: "s1"},
            {" cluster ": "Porto"}), STORE, "Porto", "trimmed name")
        self.assert_eligible(self.serve(
            parity_experiment(clusters(STORE, "cluster")), {STORE: "s1"},
            {"\tcluster\n": "Porto"}), STORE, "Porto", "control characters")
        self.clock.now = ANCHOR
        context = self.context([parity_experiment(clusters(STORE,
                                                           "cluster"))],
                               units={STORE: "s1"})
        context.set_attribute("cluster", "Lisboa")
        context.set_attribute("cluster", "Porto")
        self.clock.now = ANCHOR + 1
        self.assertEqual(draw("Porto", 0, ARMS, PARITY_SEED),
                         context.get_treatment("exp_sb"))


class SwitchbackServingTest(unittest.TestCase):

    def test_source_order_decides_whatever_the_unit_order(self):
        # With units listed user first and sources declared session first,
        # both agreeing, session serves.
        attributes = {"session_store": "s-1", "user_store": "s-1"}
        serving = switchback_serving.resolve(
            ("session_id", "user_id"),
            (SwitchbackAttributePath.parse_supported("session_store"),
             SwitchbackAttributePath.parse_supported("user_store")),
            None, {"user_id": "u1", "session_id": "x1"},
            lambda path: path.resolve(attributes))
        self.assertEqual(switchback_serving.ELIGIBLE, serving.status)
        self.assertEqual("session_id", serving.unit_type)
        self.assertEqual("x1", serving.uid)
        self.assertEqual("s-1", serving.cluster_key)

    def test_a_none_or_empty_allow_list_admits_every_value(self):
        for values in (None, (), []):
            self.assertTrue(switchback_serving.allowed(values, "s-1"))
        self.assertFalse(switchback_serving.allowed(("s-2",), "s-1"))
        self.assertIsNone(switchback_serving.allow_list([]))

    def test_sources_reject_unreadable_maps(self):
        self.assertIsNone(switchback_serving.sources(None))
        self.assertIsNone(switchback_serving.sources({}))
        self.assertIsNone(switchback_serving.sources(["a"]))
        self.assertIsNone(switchback_serving.sources({"a": None}))
        self.assertIsNone(switchback_serving.sources({"a": "x", "b": "'y"}))
        types, paths = switchback_serving.sources({"b": "x", "a": "y/z"})
        self.assertEqual(("b", "a"), types)
        self.assertEqual(("y", "z"), paths[1].keys)

    def test_legacy_serves_only_the_declared_unit_type(self):
        self.assertEqual(switchback_serving.ABSENT,
                         switchback_serving.legacy(None, {"a": "1"}).status)
        self.assertEqual(switchback_serving.ABSENT,
                         switchback_serving.legacy("b", {"a": "1"}).status)
        serving = switchback_serving.legacy("a", {"a": "1"})
        self.assertEqual(switchback_serving.INELIGIBLE, serving.status)
        self.assertEqual("a", serving.unit_type)
        self.assertIsNone(serving.cluster_key)


if __name__ == "__main__":
    unittest.main()
