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

    def test_unit_type_of_exposure(self):
        context = self.assert_winner(
            [missing_unit(1, "exp_a"), assigned(2, "exp_b")],
            "exp_b_treatment", ["exp_b"])
        self.assertEqual(UNIT_TYPE, context.exposures[0].unit)


if __name__ == "__main__":
    unittest.main()
