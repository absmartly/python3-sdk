"""Shared variable keys (Java core-api Context.getVariableAssignment): the
candidates are the experiments whose variants define the key, in id order;
the first one the unit is assigned to, overridden in or rule-assigned to
wins, and only the winner is exposed."""
import json
import unittest

from test.holdout_fixtures import (
    HOLDOUT_B_SEEDS, NORMAL_VARIANT, UNIT_TYPE, HoldoutFixture, context_data,
    experiment, holdout, with_variables)

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

    def assert_winner(self, experiments, expected, exposed, **kwargs):
        context = self.create_context(context_data(experiments), **kwargs)
        self.assertEqual(expected, context.peek_variable_value(KEY, "d"))
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(expected, context.get_variable_value(KEY, "d"))
        self.assertEqual(exposed, self.names(context))
        self.assertEqual(len(exposed), context.get_pending_count())
        # A second read exposes nothing more.
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

    def test_winner_exposure_is_the_winning_assignment(self):
        context = self.assert_winner(
            [strict_mismatch(1, "exp_a"), missing_unit(2, "exp_b"),
             assigned(3, "exp_c")],
            "exp_c_treatment", ["exp_c"])
        self.assertEqual([self.exposure(3, "exp_c", NORMAL_VARIANT)],
                         self.exposure_tuples(context.exposures))

    def test_winner_variant_without_the_key_returns_default(self):
        # The unit gets exp_a's variant 1, which does not define the key:
        # the default is returned and exp_b is never consulted or exposed.
        self.assert_winner(
            [configs(1, "exp_a", {KEY: "a0"}, {"other": "x"}),
             assigned(2, "exp_b")],
            "d", ["exp_a"])

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
        self.assert_winner(
            [missing_unit(1, "exp_a"),
             assigned(2, "exp_b", trafficSplit=[1.0, 0.0]),
             assigned(3, "exp_c")],
            "exp_b_control", ["exp_b"])

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

    def test_raising_hook_does_not_stop_the_other_holdouts(self):
        # Java collects the first failure, fires every visited candidate's
        # holdouts and rethrows before the winner is exposed.
        from sdk.context import Context

        class Raising(Context):
            def queue_exposure(self, assignment):
                if assignment.name == "h1" and \
                        not assignment.exposed.value:
                    raise RuntimeError("hook failed")
                return super().queue_exposure(assignment)

        context = self.create_context(context_data(
            [strict_mismatch(1, "exp_a", holdout_ids=[11, 12]),
             strict_mismatch(2, "exp_b", holdout_ids=[13]),
             assigned(3, "exp_c")],
            [holdout(11, "h1", HOLDOUT_B_SEEDS),
             holdout(12, "h2", HOLDOUT_B_SEEDS),
             holdout(13, "h3", HOLDOUT_B_SEEDS)]))
        context.__class__ = Raising
        with self.assertRaisesRegex(RuntimeError, "hook failed"):
            context.get_variable_value(KEY, "d")
        self.assertEqual(["h2", "h3"], self.names(context))

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


if __name__ == "__main__":
    unittest.main()
