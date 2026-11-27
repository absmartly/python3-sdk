"""Shared variable keys (Java core-api Context.getVariableAssignment): the
candidates are the experiments whose variants define the key, in id order;
the first one the unit is assigned to, overridden in or rule-assigned to
wins, and only the winner is exposed."""
import json
import unittest

from sdk.context_event_logger import EventType
from test.holdout_fixtures import (
    HOLDOUT_A_SEEDS, HOLDOUT_B_SEEDS, NORMAL_VARIANT, UID, UID_NOT_HELD_OUT,
    UNIT_TYPE, HoldoutFixture, context_data, experiment, holdout,
    with_variables)

KEY = "banner.size"
GOLD_ONLY = json.dumps(
    {"filter": [{"eq": [{"var": "tier"}, {"value": "gold"}]}]})
ASSIGN_CONTROL = json.dumps({"rules": [{"type": "assign", "variant": 0}]})


def strict_mismatch(id, name, **fields):
    # No "tier" attribute is set, so the strict audience never matches.
    return with_variables(
        experiment(id, name, audience=GOLD_ONLY, audienceStrict=True,
                   **fields), KEY, f"{name}_control", f"{name}_treatment")


def missing_unit(id, name, **fields):
    return with_variables(experiment(id, name, unit_type="device_id",
                                     **fields),
                          KEY, f"{name}_control", f"{name}_treatment")


def assigned(id, name, **fields):
    return with_variables(experiment(id, name, **fields),
                          KEY, f"{name}_control", f"{name}_treatment")


def configs(id, name, *variant_variables, **fields):
    data = experiment(id, name, **fields)
    data["variants"] = [
        {"name": f"v{i}",
         "config": None if variables is None else json.dumps(variables)}
        for i, variables in enumerate(variant_variables)]
    return data


class SharedVariableKeyTest(HoldoutFixture, unittest.TestCase):
    def setUp(self):
        self.set_up_fixture()

    def names(self, context):
        return [e.name for e in context.exposures]

    def assert_winner(self, experiments, expected, exposed, holdouts=None,
                      **kwargs):
        context = self.create_context(context_data(experiments, holdouts),
                                      **kwargs)
        self.assertEqual(expected, context.peek_variable_value(KEY, "d"))
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(expected, context.get_variable_value(KEY, "d"))
        self.assertEqual(exposed, self.names(context))
        self.assertEqual(len(exposed), context.get_pending_count())
        self.assertEqual(expected, context.get_variable_value(KEY, "d"))
        self.assertEqual(exposed, self.names(context))
        return context

    def test_lower_id_strict_audience_mismatch_is_not_exposed(self):
        for order in (1, -1):
            with self.subTest(order=order):
                self.assert_winner(
                    [strict_mismatch(1, "exp_a"),
                     assigned(2, "exp_b")][::order],
                    "exp_b_treatment", ["exp_b"])

    def test_lower_id_without_its_unit_is_not_exposed(self):
        for order in (1, -1):
            with self.subTest(order=order):
                self.assert_winner(
                    [missing_unit(1, "exp_a"), assigned(2, "exp_b")][::order],
                    "exp_b_treatment", ["exp_b"])

    def test_only_candidate_the_unit_is_not_in_is_not_exposed(self):
        # 0.3.0 exposed it; nothing wins the key now, as in Java.
        for only in (strict_mismatch(1, "exp_a"), missing_unit(1, "exp_a")):
            with self.subTest(unit_type=only["unitType"]):
                context = self.assert_winner([only], "d", [])
                context.get_treatment("exp_a")
                self.assertEqual(["exp_a"], self.names(context))

    def test_winner_exposure_is_the_winning_assignment(self):
        context = self.assert_winner(
            [strict_mismatch(1, "exp_a"), missing_unit(2, "exp_b"),
             assigned(3, "exp_c")],
            "exp_c_treatment", ["exp_c"])
        self.assertEqual([self.exposure(3, "exp_c", NORMAL_VARIANT)],
                         self.exposure_tuples(context.exposures))

    def test_winner_variant_without_the_key_returns_default(self):
        # exp_a wins with variant 1, which lacks the key: exp_b, holdout
        # included, is never consulted.
        context = self.assert_winner(
            [configs(1, "exp_a", {KEY: "a0"}, {"other": "x"}),
             assigned(2, "exp_b", holdout_ids=[12])],
            "d", ["exp_a"],
            holdouts=[holdout(12, "holdout_b", HOLDOUT_B_SEEDS)])
        self.assertEqual([], [e.name for e in context.exposures
                              if e.name == "holdout_b"])

    def test_winner_variant_without_any_config_returns_default(self):
        self.assert_winner(
            [configs(1, "exp_a", {KEY: "a0"}, None), assigned(2, "exp_b")],
            "d", ["exp_a"])

    def test_overridden_winner_variant_without_the_key_returns_default(self):
        context = self.assert_winner(
            [configs(1, "exp_a", {KEY: "a0"}, {"other": "x"}),
             assigned(2, "exp_b")],
            "d", ["exp_a"], overrides={"exp_a": 1})
        self.assertTrue(context.exposures[0].overridden)

    def test_no_candidate_assigned_returns_default_and_exposes_nothing(self):
        self.assert_winner(
            [strict_mismatch(1, "exp_a"), missing_unit(2, "exp_b")],
            "d", [])

    def test_peek_exposes_nothing(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        for _ in range(2):
            self.assertEqual("exp_b_treatment",
                             context.peek_variable_value(KEY, "d"))
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual([], self.names(context))

    def test_peek_never_falls_through_past_the_winner(self):
        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             configs(2, "exp_b", {KEY: "b0"}, {"other": "x"}),
             assigned(3, "exp_c")]))
        self.assertEqual("d", context.peek_variable_value(KEY, "d"))
        self.assertEqual(0, context.get_pending_count())

    def test_override_on_a_candidate_without_its_unit_wins(self):
        context = self.assert_winner(
            [strict_mismatch(1, "exp_a"), missing_unit(2, "exp_b"),
             assigned(3, "exp_c")],
            "exp_b_control", ["exp_b"], overrides={"exp_b": 0})
        self.assertTrue(context.exposures[0].overridden)

    def test_override_beats_the_assigned_variant(self):
        self.assert_winner(
            [missing_unit(1, "exp_a"), assigned(2, "exp_b"),
             assigned(3, "exp_c")],
            "exp_b_control", ["exp_b"], overrides={"exp_b": 0})

    def test_override_on_a_higher_id_loses_to_an_assigned_lower_id(self):
        self.assert_winner(
            [missing_unit(1, "exp_a"), assigned(2, "exp_b"),
             assigned(3, "exp_c")],
            "exp_b_treatment", ["exp_b"], overrides={"exp_c": 0})

    def test_override_on_a_higher_id_wins_over_an_unassigned_lower_id(self):
        self.assert_winner(
            [strict_mismatch(1, "exp_a"), missing_unit(2, "exp_b")],
            "exp_b_control", ["exp_b"], overrides={"exp_b": 0})

    def test_rule_on_a_candidate_without_its_unit_wins(self):
        context = self.assert_winner(
            [strict_mismatch(1, "exp_a"),
             missing_unit(2, "exp_b", assignmentRules=ASSIGN_CONTROL),
             assigned(3, "exp_c")],
            "exp_b_control", ["exp_b"])
        self.assertTrue(context.exposures[0].ruleOverride)

    def test_rule_beats_a_strict_audience_mismatch(self):
        context = self.assert_winner(
            [missing_unit(1, "exp_a"),
             strict_mismatch(2, "exp_b", assignmentRules=ASSIGN_CONTROL),
             assigned(3, "exp_c")],
            "exp_b_control", ["exp_b"])
        self.assertTrue(context.exposures[0].ruleOverride)

    def test_rule_on_a_higher_id_loses_to_an_assigned_lower_id(self):
        self.assert_winner(
            [missing_unit(1, "exp_a"), assigned(2, "exp_b"),
             assigned(3, "exp_c", assignmentRules=ASSIGN_CONTROL)],
            "exp_b_treatment", ["exp_b"])

    def test_falsy_values_are_returned_and_a_missing_key_is_the_default(self):
        cases = [(None, None), (False, False), (0, 0), (0.0, 0.0), ("", ""),
                 ({}, {}), ([], [])]
        for value, expected in cases:
            with self.subTest(value=value):
                self.setUp()
                context = self.assert_winner(
                    [missing_unit(1, "exp_a"),
                     configs(2, "exp_b", {KEY: "b0"}, {KEY: value}),
                     assigned(3, "exp_c")],
                    expected, ["exp_b"])
                self.assertIs(type(expected),
                              type(context.get_variable_value(KEY, "d")))
        with self.subTest(value="missing"):
            self.setUp()
            self.assert_winner(
                [missing_unit(1, "exp_a"),
                 configs(2, "exp_b", {KEY: "b0"}, {}),
                 assigned(3, "exp_c")],
                "d", ["exp_b"])

    def test_not_eligible_winner_is_exposed_with_control(self):
        # Outside traffic is still assigned (variant 0): it wins the key.
        context = self.assert_winner(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", trafficSplit=[1.0, 0.0]),
             assigned(3, "exp_c")],
            "exp_b_control", ["exp_b"])
        self.assertFalse(context.exposures[0].eligible)

    def test_losing_candidate_fires_only_its_holdouts(self):
        # Java fires the applicable holdouts of every candidate visited on
        # the non-peek path; the candidate's own exposure is never queued.
        loser = strict_mismatch(1, "exp_a", holdout_ids=[12])
        context = self.create_context(context_data(
            [loser, assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        self.assertEqual("exp_b_treatment",
                         context.peek_variable_value(KEY, "d"))
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(
            [self.holdout_exposure(12, "holdout_b", 1),
             self.exposure(2, "exp_b", NORMAL_VARIANT)],
            self.exposure_tuples(context.exposures))
        self.assertFalse(context.get_assignment("exp_a").exposed.value)

    def test_losing_candidate_holdouts_go_through_a_queue_exposure_hook(self):
        from sdk.context import Context
        offered = []

        class Recording(Context):
            def queue_exposure(self, assignment):
                offered.append(assignment.name)
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.__class__ = Recording
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["holdout_b", "exp_b"], offered)
        self.assertEqual(["holdout_b", "exp_b"], self.names(context))
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["holdout_b", "exp_b"], offered)

    def test_losing_candidate_holdouts_are_not_queued_while_closing(self):
        from sdk.context_error import ContextError
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        # Closing starts after the read's readiness check, while the
        # candidates are being resolved.
        get_assignment = context.get_assignment
        context.get_assignment = \
            lambda name: context.closing.set(True) or get_assignment(name)
        with self.assertRaises(ContextError):
            context.get_variable_value(KEY, "d")
        self.assertEqual([], self.names(context))
        self.assertEqual(0, context.get_pending_count())
        self.assertFalse(
            context._holdout_assignments[(12, UNIT_TYPE)].exposed.value)
        # A failed close reopens the context: the next read still queues
        # the holdout the closing read could not.
        context.get_assignment = get_assignment
        context.closing.set(False)
        self.assertFalse(context.get_assignment("exp_a").holdouts_exposed)
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["holdout_b", "exp_b"], self.names(context))

    def test_losing_candidate_holdout_is_named_from_its_snapshot(self):
        # The arm is cached under the old name; a same-iteration rename
        # keeps it, and the exposure carries the payload's current name.
        context = self.create_context(context_data(
            [assigned(3, "exp_c", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.peek_treatment("exp_c")
        self.refresh(context, context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "renamed", HOLDOUT_B_SEEDS)]))
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["renamed", "exp_b"], self.names(context))

    def test_warm_read_takes_no_event_lock(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.get_variable_value(KEY, "d")
        for name in ("exp_a", "exp_b"):
            self.assertTrue(context.get_assignment(name).holdouts_exposed)
        calls = []
        acquire = context.event_lock.acquire_write
        context.event_lock.acquire_write = \
            lambda: calls.append(1) or acquire()
        scans = []
        context._holdouts_unexposed = \
            lambda assignment: scans.append(1) or True
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual([], calls)
        self.assertEqual([], scans)

    def test_holdouts_exposed_by_a_treatment_take_no_event_lock(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b"), assigned(3, "exp_c", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.get_treatment("exp_c")
        context.get_treatment("exp_b")
        calls = []
        acquire = context.event_lock.acquire_write
        context.event_lock.acquire_write = \
            lambda: calls.append(1) or acquire()
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual([], calls)
        self.assertTrue(context.get_assignment("exp_a").holdouts_exposed)

    def test_hook_winner_holdouts_leave_nothing_pending(self):
        # Through a queue_exposure override, a variable read that exposes
        # the winner and its holdouts leaves no holdout pending, so later
        # treatment reads take no event lock.
        from sdk.context import Context

        class PassThrough(Context):
            def queue_exposure(self, assignment):
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [assigned(1, "exp_a", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.__class__ = PassThrough
        context.get_variable_value(KEY, "d")
        self.assertEqual(["holdout_b", "exp_a"], self.names(context))
        self.assertFalse(context.get_assignment("exp_a").holdouts_pending)
        calls = []
        acquire = context.event_lock.acquire_write
        context.event_lock.acquire_write = \
            lambda: calls.append(1) or acquire()
        for _ in range(3):
            context.get_treatment("exp_a")
        self.assertEqual([], calls)

    def test_losing_candidate_holdouts_use_its_exposure_time(self):
        # Like Context._expose: a candidate resolved with an exposure time
        # (get_treatment(name, exposed_at)) stamps its holdouts with it.
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.get_assignment("exp_a").exposedAt = 123
        context.get_variable_value(KEY, "d")
        self.assertEqual([("holdout_b", 123), ("exp_b", self.clock.millis())],
                         [(e.name, e.exposedAt) for e in context.exposures])

    def test_holdout_a_hook_declines_is_offered_again(self):
        from sdk.context import Context
        declined = []

        class Declining(Context):
            def queue_exposure(self, assignment):
                if assignment.name == "holdout_b" and not declined:
                    declined.append(1)
                    return None
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.__class__ = Declining
        context.get_variable_value(KEY, "d")
        self.assertEqual(["exp_b"], self.names(context))
        self.assertFalse(context.get_assignment("exp_a").holdouts_exposed)
        context.get_variable_value(KEY, "d")
        self.assertEqual(["exp_b", "holdout_b"], self.names(context))
        self.assertTrue(context.get_assignment("exp_a").holdouts_exposed)

    def test_winner_holdout_a_hook_declines_is_offered_once_per_read(self):
        # The walk offers the winner's holdouts; queuing the winner's own
        # exposure must not offer a declined one again in the same read.
        from sdk.context import Context
        offered = []

        class Declining(Context):
            def queue_exposure(self, assignment):
                offered.append(assignment.name)
                if assignment.name == "holdout_b" and \
                        offered.count("holdout_b") == 1:
                    return None
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [assigned(1, "exp_a", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.__class__ = Declining
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["holdout_b", "exp_a"], offered)
        self.assertEqual(["exp_a"], self.names(context))
        self.assertTrue(context.get_assignment("exp_a").holdouts_pending)
        context.get_variable_value(KEY, "d")
        self.assertEqual(["holdout_b", "exp_a", "holdout_b"], offered)
        self.assertEqual(["exp_a", "holdout_b"], self.names(context))
        self.assertFalse(context.get_assignment("exp_a").holdouts_pending)
        context.get_variable_value(KEY, "d")
        self.assertEqual(3, len(offered))

    def test_raising_hook_does_not_stop_the_other_holdouts(self):
        # Java collects the first failure, fires every visited candidate's
        # holdouts and rethrows before the winner is exposed.
        from sdk.context import Context

        offered = []

        class Raising(Context):
            def queue_exposure(self, assignment):
                offered.append(assignment.name)
                if assignment.name in ("h1", "h2") and \
                        not assignment.exposed.value:
                    raise RuntimeError(assignment.name + " failed")
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[11, 12]),
             strict_mismatch(2, "exp_b", holdout_ids=[13]),
             assigned(3, "exp_c")],
            [holdout(11, "h1", HOLDOUT_B_SEEDS),
             holdout(12, "h2", HOLDOUT_B_SEEDS),
             holdout(13, "h3", HOLDOUT_B_SEEDS)]))
        context.__class__ = Raising
        with self.assertRaisesRegex(RuntimeError, "h1 failed"):
            context.get_variable_value(KEY, "d")
        self.assertEqual(["h1", "h2", "h3"], offered)
        self.assertEqual(["h3"], self.names(context))

    def test_losing_candidate_holdout_exposure_is_logged(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.get_variable_value(KEY, "d")
        self.assertEqual(["holdout_b", "exp_b"],
                         [e.name for e in self.exposure_events()])

    def test_override_to_a_missing_variant_still_wins(self):
        # Java: an overridden candidate wins even when the override names a
        # variant the experiment does not have; it has no variables, so the
        # default is returned and only it is exposed.
        context = self.assert_winner(
            [assigned(1, "exp_a"), assigned(2, "exp_b")],
            "d", ["exp_a"], overrides={"exp_a": 5})
        self.assertEqual(
            [self.exposure(1, "exp_a", 5, assigned=False, overridden=True)],
            self.exposure_tuples(context.exposures))

    def test_unit_type_of_exposure(self):
        context = self.assert_winner(
            [missing_unit(1, "exp_a"), assigned(2, "exp_b")],
            "exp_b_treatment", ["exp_b"])
        self.assertEqual(UNIT_TYPE, context.exposures[0].unit)

    def test_no_winner_still_fires_the_holdouts_of_both_arms(self):
        # Java fires the holdouts of every visited candidate even when none
        # wins, so held-out and not held-out units both publish the holdout.
        # The held-out unit gets the suppressed fallback's control value.
        for uid, arm, value in ((UID, 0, "exp_a_control"),
                                (UID_NOT_HELD_OUT, 1, "d")):
            with self.subTest(arm=arm):
                self.setUp()
                context = self.create_context(context_data(
                    [strict_mismatch(1, "exp_a", holdout_ids=[11])],
                    [holdout(11, "holdout_a", HOLDOUT_A_SEEDS)]),
                    units={UNIT_TYPE: uid})
                self.assertEqual(value,
                                 context.get_variable_value(KEY, "d"))
                self.assertEqual(
                    [self.holdout_exposure(11, "holdout_a", arm)],
                    self.exposure_tuples(context.exposures))

    def test_warm_read_without_holdouts_skips_the_holdout_pass(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        context.get_variable_value(KEY, "d")
        calls = []
        context._expose_holdouts = lambda assignment: calls.append(1)
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual([], calls)

    def test_set_unit_during_the_walk_walks_the_key_again(self):
        # Both candidates' units are missing when the read starts. set_unit
        # retires exp_a after the walk resolved it, so exp_b is never the
        # first eligible candidate: the read walks again and exp_a wins.
        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", unit_type="user_id")]), units={})
        get_assignment = context.get_assignment
        resolved = []

        def set_units_after_exp_a(name, exposed_at=None):
            assignment = get_assignment(name, exposed_at=exposed_at)
            resolved.append(name)
            if resolved == ["exp_a"]:
                context.set_unit("device_id", UID)
                context.set_unit("user_id", UID)
            return assignment

        context.get_assignment = set_units_after_exp_a
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        context.get_assignment = get_assignment
        self.assertEqual(["exp_a"], self.names(context))
        self.assertEqual("exp_a_treatment",
                         context.peek_variable_value(KEY, "d"))

    def test_set_unit_after_a_candidate_was_checked_walks_the_key_again(self):
        # The units arrive after exp_a was checked (and not retired at that
        # point) but before exp_b is looked up: exp_b would win a key exp_a
        # now wins, so the read walks again instead of exposing exp_b.
        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", unit_type="user_id")]), units={})
        get_assignment = context.get_assignment

        def set_units_before_exp_b(name, exposed_at=None):
            if name == "exp_b" and context.get_unit("user_id") is None:
                context.set_unit("device_id", UID)
                context.set_unit("user_id", UID)
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = set_units_before_exp_b
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        context.get_assignment = get_assignment
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_a"], self.names(context))

    def test_set_unit_with_a_unit_already_set_does_not_walk_again(self):
        # Only a newly added unit retires assignments; setting the same UID
        # again during the walk must not make the read walk a second time.
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        get_assignment = context.get_assignment
        resolved = []

        def set_same_unit(name, exposed_at=None):
            resolved.append(name)
            context.set_unit(UNIT_TYPE, UID)
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = set_same_unit
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_a", "exp_b"], resolved)

    def test_peek_walks_the_key_again_when_a_unit_arrives(self):
        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", unit_type="user_id")]), units={})
        get_assignment = context.get_assignment

        def set_units_before_exp_b(name, exposed_at=None):
            if name == "exp_b" and context.get_unit("user_id") is None:
                context.set_unit("device_id", UID)
                context.set_unit("user_id", UID)
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = set_units_before_exp_b
        self.assertEqual("exp_a_treatment",
                         context.peek_variable_value(KEY, "d"))
        self.assertEqual(0, context.get_pending_count())

    def test_invalidated_walk_offers_no_holdouts_before_walking_again(self):
        # The stale walk passes exp_m, a loser with a holdout; the retry
        # stops at exp_a and never visits exp_m, so its holdout never fires.
        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             strict_mismatch(2, "exp_m", holdout_ids=[12]),
             assigned(3, "exp_b", unit_type="user_id")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]),
            units={UNIT_TYPE: UID, "user_id": UID})
        get_assignment = context.get_assignment

        def set_unit_before_exp_b(name, exposed_at=None):
            if name == "exp_b" and context.get_unit("device_id") is None:
                context.set_unit("device_id", UID)
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = set_unit_before_exp_b
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_a"], self.names(context))

    def test_unit_added_by_a_hook_during_the_holdout_pass_walks_again(self):
        # The override adds exp_a's unit while it is offered exp_b's
        # holdout; exp_b (user_id) is not retired, so only re-checking after
        # the holdout pass makes the read return and expose exp_a.
        from sdk.context import Context

        class SettingUnit(Context):
            def queue_exposure(self, assignment):
                if assignment.name == "holdout_b" and \
                        self.get_unit("device_id") is None:
                    self.set_unit("device_id", UID)
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", unit_type="user_id", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS, unit_type="user_id")]),
            units={"user_id": UID})
        context.__class__ = SettingUnit
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertNotIn("exp_b", self.names(context))
        self.assertIn("exp_a", self.names(context))

    def test_cached_override_of_an_experiment_a_refresh_removed_cannot_win(
            self):
        # exp_a's override is cached with its real id; the refresh lands
        # after the walk read the index, so the cache alone would let it win.
        context = self.create_context(context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]),
            overrides={"exp_a": 1})
        context.get_assignment("exp_a")
        get_assignment = context.get_assignment
        refreshed = []

        def refresh_first(name, exposed_at=None):
            if not refreshed:
                refreshed.append(name)
                self.refresh(context, context_data([assigned(2, "exp_b")]))
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = refresh_first
        for read in (context.peek_variable_value,
                     context.get_variable_value):
            refreshed.clear()
            self.refresh(context, context_data(
                [assigned(1, "exp_a"), assigned(2, "exp_b")]))
            context.get_assignment = get_assignment
            context.get_assignment("exp_a")
            context.get_assignment = refresh_first
            with self.subTest(read=read.__name__):
                self.assertEqual("exp_b_treatment", read(KEY, "d"))
        context.get_assignment = get_assignment
        self.assertEqual([self.exposure(2, "exp_b", NORMAL_VARIANT)],
                         self.exposure_tuples(context.exposures))

    def test_experiment_a_refresh_adds_during_the_walk_wins(self):
        # The walk read the old index (only exp_b); the refresh adds the
        # overridden, lower-id exp_a, which wins the key in the new data.
        for read in ("peek_variable_value", "get_variable_value"):
            with self.subTest(read=read):
                self.setUp()
                context = self.create_context(
                    context_data([assigned(2, "exp_b")]),
                    overrides={"exp_a": 1})
                get_assignment = context.get_assignment
                refreshed = []

                def refresh_first(name, exposed_at=None):
                    if not refreshed:
                        refreshed.append(name)
                        self.refresh(context, context_data(
                            [assigned(1, "exp_a"), assigned(2, "exp_b")]))
                    return get_assignment(name, exposed_at=exposed_at)

                context.get_assignment = refresh_first
                self.assertEqual("exp_a_treatment",
                                 getattr(context, read)(KEY, "d"))
                self.assertNotIn("exp_b", self.names(context))

    def test_read_that_never_sees_one_state_returns_the_default(self):
        # Every walk sees exp_a removed right after its cached override was
        # resolved and restored by the time it reaches exp_m. No attempt
        # sees one coherent state, so the read returns the default and
        # exposes nothing, holdouts included, rather than a winner neither
        # payload would give on its own.
        holdouts = [holdout(13, "holdout_m", HOLDOUT_B_SEEDS)]
        others = [strict_mismatch(2, "exp_m", holdout_ids=[13]),
                  assigned(3, "exp_b")]
        full = context_data([assigned(1, "exp_a")] + others, holdouts)
        context = self.create_context(full, overrides={"exp_a": 1})
        context.get_assignment("exp_a")
        get_assignment = context.get_assignment

        def flip(name, exposed_at=None):
            if name == "exp_a":
                assignment = get_assignment(name, exposed_at=exposed_at)
                self.refresh(context, context_data(others, holdouts))
                return assignment
            if name == "exp_m":
                self.refresh(context, full)
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = flip
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        self.assertEqual([], self.names(context))
        context.get_assignment = get_assignment
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))

    def test_override_placeholder_cached_before_a_refresh_adds_the_experiment(
            self):
        # peek_treatment caches exp_a's override while exp_a is missing (id
        # 0); once a refresh adds it, the read must resolve it again and win
        # with its real id, not return the default with an id-0 exposure.
        context = self.create_context(context_data([assigned(2, "exp_b")]),
                                      overrides={"exp_a": 1})
        context.peek_treatment("exp_a")
        self.refresh(context, context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]))
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(
            [self.exposure(1, "exp_a", 1, assigned=False, overridden=True)],
            self.exposure_tuples(context.exposures))

    def test_warm_shared_key_read_takes_no_data_lookup(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        context.get_variable_value(KEY, "d")
        calls = []
        get_experiment = context.get_experiment
        context.get_experiment = \
            lambda name: calls.append(name) or get_experiment(name)
        for _ in range(3):
            self.assertEqual("exp_b_treatment",
                             context.get_variable_value(KEY, "d"))
        self.assertEqual([], calls)

    def test_refresh_by_a_hook_during_the_holdout_pass_walks_again(self):
        # The override refreshes in a lower-id overridden exp_a while it is
        # offered exp_b's holdout; only re-checking the index after the
        # holdout pass makes the read return and expose exp_a.
        from sdk.context import Context
        fixture = self
        holdouts = [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]

        class Refreshing(Context):
            def queue_exposure(self, assignment):
                if assignment.name == "holdout_b" and \
                        self.get_experiment("exp_a") is None:
                    fixture.refresh(self, context_data(
                        [assigned(1, "exp_a"),
                         assigned(2, "exp_b", holdout_ids=[12])], holdouts))
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [assigned(2, "exp_b", holdout_ids=[12])], holdouts),
            overrides={"exp_a": 1})
        context.__class__ = Refreshing
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertNotIn("exp_b", self.names(context))

    def test_index_is_read_under_the_data_lock(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        lock = context.data_lock
        held = []
        acquire, release = lock.acquire_write, lock.release_write
        state = {"in": False}

        def acquire_write():
            acquire()
            state["in"] = True

        def release_write():
            state["in"] = False
            release()

        class Index(dict):
            def get(self, key, default=None):
                held.append(state["in"])
                return dict.get(self, key, default)

        lock.acquire_write, lock.release_write = acquire_write, release_write
        context.index_variables = Index(context.index_variables)
        context.get_variable_value(KEY, "d")
        self.assertEqual([True], held)
        # The index the walk compares against is read under the lock too: a
        # refresh between the two reads must make the read walk again.
        index_reads = []
        cls = type(context)

        class Watching(cls):
            @property
            def index(self):
                index_reads.append(state["in"])
                return self.__dict__["index"]

            @index.setter
            def index(self, value):
                self.__dict__["index"] = value

        context.__class__ = Watching
        context.get_variable_value(KEY, "d")
        self.assertTrue(index_reads)
        self.assertTrue(index_reads[0])

    def test_exposed_override_is_not_exposed_again_after_its_removal(self):
        # As on 0.3.0 and in JS: the cached override survives a refresh that
        # removes its experiment, so get_treatment does not expose it twice.
        context = self.create_context(context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]),
            overrides={"exp_a": 1})
        self.assertEqual(1, context.get_treatment("exp_a"))
        for _ in range(3):
            self.refresh(context, context_data([assigned(2, "exp_b")]))
            self.assertEqual(1, context.get_treatment("exp_a"))
            self.refresh(context, context_data(
                [assigned(1, "exp_a"), assigned(2, "exp_b")]))
            self.assertEqual(1, context.get_treatment("exp_a"))
        self.assertEqual(
            [self.exposure(1, "exp_a", 1, assigned=False, overridden=True)],
            self.exposure_tuples(context.exposures))

    def test_exposed_override_is_not_exposed_again_when_its_id_changes(self):
        context = self.create_context(context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]),
            overrides={"exp_a": 1})
        self.assertEqual(1, context.get_treatment("exp_a"))
        self.refresh(context, context_data(
            [assigned(5, "exp_a"), assigned(2, "exp_b")]))
        self.assertEqual(1, context.get_treatment("exp_a"))
        self.assertEqual(
            [self.exposure(1, "exp_a", 1, assigned=False, overridden=True)],
            self.exposure_tuples(context.exposures))

    def test_override_kept_from_before_an_id_0_experiment_gets_its_value(
            self):
        # The override is cached while exp_a is missing; a refresh adds exp_a
        # with id 0, so the cache keeps the override, which must then carry
        # the experiment's variables instead of returning the default.
        context = self.create_context(context_data([assigned(2, "exp_b")]),
                                      overrides={"exp_a": 1})
        context.peek_treatment("exp_a")
        self.refresh(context, context_data(
            [assigned(0, "exp_a"), assigned(2, "exp_b")]))
        self.assertEqual("exp_a_treatment",
                         context.peek_variable_value(KEY, "d"))
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))

    def test_kept_override_keeps_its_variables_across_a_config_change(self):
        context = self.create_context(context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]),
            overrides={"exp_a": 1})
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        changed = with_variables(experiment(1, "exp_a"), KEY,
                                 "exp_a_control2", "exp_a_t2")
        self.refresh(context, context_data([changed, assigned(2, "exp_b")]))
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))

    def test_negative_override_never_reads_a_variant_from_the_end(self):
        context = self.create_context(context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]),
            overrides={"exp_a": -1})
        self.assertEqual(["d", "d", "d"],
                         [context.get_variable_value(KEY, "d"),
                          context.get_variable_value(KEY, "d"),
                          context.peek_variable_value(KEY, "d")])

    def test_override_to_a_missing_variant_takes_it_once_a_refresh_adds_it(
            self):
        # Same experiment (id 1) throughout: the kept override gets the new
        # variant's variables, as JS followArm does.
        two = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"})
        context = self.create_context(context_data(
            [two, assigned(9, "exp_b")]), overrides={"exp_a": 2})
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        three = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"}, {KEY: "a2"})
        self.refresh(context, context_data([three, assigned(9, "exp_b")]))
        self.assertEqual(["a2", "a2"],
                         [context.get_variable_value(KEY, "d"),
                          context.peek_variable_value(KEY, "d")])
        self.assertEqual(["exp_a"], self.names(context))

    def test_override_to_a_missing_variant_of_a_reidentified_experiment(
            self):
        # The override names a variant exp_a does not have; a refresh adds
        # that variant but also gives exp_a a new id: the kept override is
        # not for the same experiment, so it does not take the new value.
        two = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"})
        context = self.create_context(context_data(
            [two, assigned(9, "exp_b")]), overrides={"exp_a": 2})
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        three = configs(7, "exp_a", {KEY: "a0"}, {KEY: "a1"}, {KEY: "a2"})
        self.refresh(context, context_data([three, assigned(9, "exp_b")]))
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_a"], self.names(context))

    def test_override_of_an_experiment_with_id_0_is_exposed_once(self):
        context = self.create_context(context_data([assigned(0, "exp_a")]),
                                      overrides={"exp_a": 1})
        for _ in range(3):
            self.assertEqual("exp_a_treatment",
                             context.get_variable_value(KEY, "d"))
            self.assertEqual(1, context.get_treatment("exp_a"))
        self.assertEqual(1, context.get_pending_count())

    def test_final_walk_replaced_by_a_keyless_experiment_exposes_nothing(
            self):
        # On every walk a refresh swaps exp_a for a same-name experiment
        # that no longer defines the key. The final walk must not expose
        # that replacement or return its default as if it had won.
        keyed = assigned(1, "exp_a")
        keyless = configs(1, "exp_a", {"other": "x"}, {"other": "y"})
        context = self.create_context(context_data(
            [keyed, assigned(2, "exp_b")]))
        get_assignment = context.get_assignment

        def swap(name, exposed_at=None):
            if name == "exp_a":
                self.refresh(context, context_data(
                    [keyless, assigned(2, "exp_b")]))
                assignment = get_assignment(name, exposed_at=exposed_at)
                self.refresh(context, context_data(
                    [keyed, assigned(2, "exp_b")]))
                return assignment
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = swap
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        self.assertEqual([], self.names(context))

    def test_declined_holdout_is_offered_once_per_read_across_retries(self):
        # The hook declines holdout_b and adds an unrelated unit, so the
        # read walks again; the retry must not offer holdout_b a second
        # time in the same read. The next read offers it again.
        from sdk.context import Context
        offered = []

        class Declining(Context):
            def queue_exposure(self, assignment):
                offered.append(assignment.name)
                if assignment.name == "holdout_b":
                    if self.get_unit("other_id") is None:
                        self.set_unit("other_id", UID)
                    return None
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.__class__ = Declining
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(1, offered.count("holdout_b"))
        context.get_variable_value(KEY, "d")
        self.assertEqual(2, offered.count("holdout_b"))

    def test_close_on_a_shared_holdout_reached_through_a_loser(self):
        # exp_a loses and shares holdout_b with the winner exp_b. Closing
        # from the logger on holdout_b must publish exp_b with it.
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))

        def close_on_holdout(event_type, data):
            if event_type == EventType.EXPOSURE and \
                    data.name == "holdout_b":
                self.logger.on_event = None
                context.close_async()

        self.logger.on_event = close_on_holdout
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.client.wait_for_publish(1)
        self.assertEqual(
            [self.holdout_exposure(12, "holdout_b", 1),
             self.exposure(2, "exp_b", NORMAL_VARIANT)],
            self.exposure_tuples(self.client.published[0].exposures))

    def test_shared_holdout_loser_is_skipped_on_warm_reads(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.get_variable_value(KEY, "d")
        self.assertTrue(context.get_assignment("exp_a").holdouts_exposed)
        self.assertEqual(["holdout_b", "exp_b"], self.names(context))

    def test_override_variables_fill_reads_the_payload_it_stores(self):
        # The read passes the cache check while exp_a's variant 2 is X; a
        # refresh changes it to Y before the fill. The fill must store Y,
        # the payload current when it stores, not the X it checked.
        two = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"})
        with_x = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"}, {KEY: "X"})
        with_y = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"}, {KEY: "Y"})
        context = self.create_context(context_data(
            [two, assigned(9, "exp_b")]), overrides={"exp_a": 2})
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        self.refresh(context, context_data([with_x, assigned(9, "exp_b")]))
        lock = context.context_lock
        acquire_write = lock.acquire_write
        refreshed = []

        def refresh_before_the_fill():
            lock.acquire_write = acquire_write
            refreshed.append(1)
            self.refresh(context, context_data(
                [with_y, assigned(9, "exp_b")]))
            acquire_write()

        lock.acquire_write = refresh_before_the_fill
        self.assertEqual("Y", context.peek_variable_value(KEY, "d"))
        self.assertEqual([1], refreshed)
        self.assertEqual("Y", context.get_variable_value(KEY, "d"))

    def test_override_fill_skips_an_experiment_a_refresh_reidentified(self):
        # The read passes the cache check for exp_a (id 1); a refresh moves
        # exp_a to id 5 before the fill. The kept override is no longer for
        # the same experiment, so the fill stores nothing.
        two = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"})
        with_x = configs(1, "exp_a", {KEY: "a0"}, {KEY: "a1"}, {KEY: "X"})
        moved = configs(5, "exp_a", {KEY: "a0"}, {KEY: "a1"}, {KEY: "Y"})
        context = self.create_context(context_data(
            [two, assigned(9, "exp_b")]), overrides={"exp_a": 2})
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        self.refresh(context, context_data([with_x, assigned(9, "exp_b")]))
        lock = context.context_lock
        acquire_write = lock.acquire_write

        def refresh_before_the_fill():
            lock.acquire_write = acquire_write
            self.refresh(context, context_data(
                [moved, assigned(9, "exp_b")]))
            acquire_write()

        lock.acquire_write = refresh_before_the_fill
        self.assertEqual("d", context.peek_variable_value(KEY, "d"))
        self.assertIsNone(context.get_assignment("exp_a").variables)

    def test_loser_sharing_a_holdout_keeps_it_pending_if_the_winner_fails(
            self):
        # exp_a loses and shares holdout_b with the winner exp_b, so the
        # arm waits for exp_b's section. A close then rejects exp_b and
        # fails; a refresh removes the holdout from exp_b. The next read must
        # still publish holdout_b through exp_a.
        from sdk.context_error import ContextError
        holdouts = [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b", holdout_ids=[12])], holdouts))
        expose_winner = context._expose_winner

        def closing(assignment):
            context.closing.set(True)
            try:
                return expose_winner(assignment)
            finally:
                context.closing.set(False)

        context._expose_winner = closing
        with self.assertRaises(ContextError):
            context.get_variable_value(KEY, "d")
        context._expose_winner = expose_winner
        self.assertEqual([], self.names(context))
        self.refresh(context, context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")], holdouts))
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["holdout_b", "exp_b"], self.names(context))

    def test_winner_retired_on_every_attempt_returns_the_default(self):
        # set_unit retires the winner each time it is about to be exposed;
        # after the last attempt the read returns the default, not the value
        # of a winner that was never exposed.
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        expose_winner = context._expose_winner
        attempts = []

        def retire_first(assignment):
            attempts.append(assignment.name)
            context._retire(assignment)
            return expose_winner(assignment)

        context._expose_winner = retire_first
        self.assertEqual("d", context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_b", "exp_b", "exp_b"], attempts)
        self.assertEqual([], self.names(context))

    def test_hook_returning_false_is_a_decline_not_a_retirement(self):
        # v0.2.4 hooks may return False. Without holdouts that must not look
        # like set_unit retiring the winner: the value comes back and the
        # hook is called once per read, as in 0.3.0.
        from sdk.context import Context
        calls = []

        class Declining(Context):
            def queue_exposure(self, assignment):
                calls.append(assignment.name)
                return False

        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a"), assigned(2, "exp_b")]))
        context.__class__ = Declining
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_b"], calls)
        self.assertEqual(NORMAL_VARIANT, context.get_treatment("exp_b"))
        self.assertEqual(["exp_b", "exp_b"], calls)

    def test_hook_seeing_the_winner_retired_walks_the_key_again(self):
        # Without holdouts: exp_a (user_id) is missing its unit, so exp_b
        # wins. Its override, while being offered exp_b, adds user_id and
        # retires exp_b, the winner it was offered, then does not queue it.
        # Judged by the assignment's state, the read walks again and exp_a
        # wins.
        from sdk.context import Context

        class SettingUnit(Context):
            def queue_exposure(self, assignment):
                if assignment.name == "exp_b" and \
                        self.get_unit("user_id") is None:
                    self.set_unit("user_id", UID)
                    self._retire(assignment)
                    return None
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [assigned(1, "exp_a", unit_type="user_id"),
             assigned(2, "exp_b")]))
        context.__class__ = SettingUnit
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_a"], self.names(context))

    def test_treatment_hook_judged_by_state_after_it_adds_the_unit(self):
        # exp_a is overridden on a missing unit. On its first call the hook
        # adds the unit (retiring the assignment it was handed) without
        # queuing it; get_treatment must resolve again and queue exactly one
        # exposure for the fresh assignment.
        from sdk.context import Context
        seen = []

        class SettingUnit(Context):
            def queue_exposure(self, assignment):
                seen.append(self.get_unit("device_id"))
                if self.get_unit("device_id") is None:
                    self.set_unit("device_id", "dev-1")
                    return None
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [missing_unit(1, "exp_a")]), units={}, overrides={"exp_a": 1})
        context.__class__ = SettingUnit
        self.assertEqual(1, context.get_treatment("exp_a"))
        self.assertEqual([None, "dev-1"], seen)
        self.assertEqual(1, context.get_pending_count())

    def test_hook_is_never_handed_a_retired_assignment(self):
        # set_unit lands between resolving the assignment and exposing it:
        # the hook is called once, with the fresh assignment.
        from sdk.context import Context
        handed = []

        class Recording(Context):
            def queue_exposure(self, assignment):
                handed.append((assignment.retired, assignment.assigned))
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [missing_unit(1, "exp_a")]), units={})
        context.__class__ = Recording
        get_assignment = context.get_assignment
        calls = []

        def set_unit_after_first(name, exposed_at=None):
            assignment = get_assignment(name, exposed_at=exposed_at)
            if not calls:
                calls.append(name)
                context.set_unit("device_id", "dev-1")
            return assignment

        context.get_assignment = set_unit_after_first
        context.get_treatment("exp_a")
        self.assertEqual([(False, True)], handed)
        self.assertEqual(1, context.get_pending_count())

    def test_set_unit_retiring_the_winner_before_exposure_walks_again(self):
        # exp_b wins while exp_a's unit is missing; the unit arrives as
        # exp_b is exposed and retires it, so the read walks again and
        # returns and exposes exp_a, which wins with the unit.
        context = self.create_context(context_data(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", unit_type="device_id",
                      holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS,
                     unit_type="device_id")]),
            units={}, overrides={"exp_b": 1})
        expose_winner = context._expose_winner
        calls = []

        def set_unit_first(assignment):
            if not calls:
                calls.append(assignment.name)
                context.set_unit("device_id", UID)
            return expose_winner(assignment)

        context._expose_winner = set_unit_first
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual(["exp_b"], calls)
        self.assertEqual(["exp_a"], self.names(context))

    def test_warm_read_skips_holdouts_already_exposed(self):
        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[12]),
             assigned(2, "exp_b")],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))
        context.get_variable_value(KEY, "d")
        calls = []
        expose_holdouts = context._expose_holdouts
        context._expose_holdouts = \
            lambda assignment: calls.append(1) or expose_holdouts(assignment)
        for _ in range(3):
            self.assertEqual("exp_b_treatment",
                             context.get_variable_value(KEY, "d"))
        self.assertEqual([], calls)

    def test_experiment_removed_by_a_refresh_during_the_walk_cannot_win(self):
        # exp_a is overridden, so its placeholder would claim the key once a
        # refresh removed it; the remaining candidate wins instead.
        context = self.create_context(context_data(
            [assigned(1, "exp_a"), assigned(2, "exp_b")]),
            overrides={"exp_a": 1})
        get_assignment = context.get_assignment
        refreshed = []

        def refresh_first(name, exposed_at=None):
            if not refreshed:
                refreshed.append(name)
                self.refresh(context, context_data([assigned(2, "exp_b")]))
            return get_assignment(name, exposed_at=exposed_at)

        context.get_assignment = refresh_first
        self.assertEqual("exp_b_treatment",
                         context.get_variable_value(KEY, "d"))
        self.assertEqual([self.exposure(2, "exp_b", NORMAL_VARIANT)],
                         self.exposure_tuples(context.exposures))

    def test_close_cannot_publish_the_winner_holdouts_without_the_winner(self):
        # Closing from the logger on the holdout exposure publishes the
        # winner's whole group, accepted before the logger runs.
        context = self.create_context(context_data(
            [assigned(1, "exp_a", holdout_ids=[12])],
            [holdout(12, "holdout_b", HOLDOUT_B_SEEDS)]))

        def close_on_holdout(event_type, data):
            if event_type == EventType.EXPOSURE and \
                    data.name == "holdout_b":
                self.logger.on_event = None
                context.close_async()

        self.logger.on_event = close_on_holdout
        self.assertEqual("exp_a_treatment",
                         context.get_variable_value(KEY, "d"))
        self.client.wait_for_publish(1)
        self.assertEqual(
            [self.holdout_exposure(12, "holdout_b", 1),
             self.exposure(1, "exp_a", NORMAL_VARIANT)],
            self.exposure_tuples(self.client.published[0].exposures))


if __name__ == "__main__":
    unittest.main()
