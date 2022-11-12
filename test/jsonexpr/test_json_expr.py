import unittest

from sdk.jsonexpr.json_expr import JsonExpr


class JsonExprTest(unittest.TestCase):
    json_expr = JsonExpr()

    john = {"age": 20, "language": "en-US", "returning": False}
    terry = {"age": 20, "language": "en-GB", "returning": True}
    kate = {"age": 50, "language": "es-ES", "returning": False}
    maria = {"age": 52, "language": "pt-PT", "returning": True}

    age_twenty_and_us = [{
        "eq": [{"var": {
            "path": "age"
        }}, {
            "value": 20
        }]
    }, {
        "eq": [{"var": {
            "path": "language"
        }}, {
            "value": "en-US"
        }]
    }]
    age_over_fifty = [{
        "gte": [{"var": {
            "path": "age"
        }}, {
            "value": 50
        }]
    }]
    age_twenty_and_us_or_age_over_fifty = [{
        "or": [age_twenty_and_us, age_over_fifty]
    }]

    returning = [{"var": {
        "path": "returning"
    }}]

    returning_and_age_twenty_and_us_or_age_over_fifty = [{"var": {
        "path": "returning"
    }}, age_twenty_and_us_or_age_over_fifty]

    not_returning_and_spanish = [{"not": {
        "var": {
            "path": "returning"
        }
    }},
        {"eq": [{"var": {
            "path": "language"
        }}, {
            "value": "es-ES"
        }]}
    ]

    def test_age_twenty_as_us_english(self):
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us, self.john))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us, self.terry))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us, self.kate))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us, self.maria))

    def test_age_over_fifty(self):
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.age_over_fifty, self.john))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.age_over_fifty, self.terry))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.age_over_fifty, self.kate))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.age_over_fifty, self.maria))

    def test_age_twenty_and_us_or_age_over_fifty(self):
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us_or_age_over_fifty, self.john))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us_or_age_over_fifty, self.terry))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us_or_age_over_fifty, self.kate))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.age_twenty_and_us_or_age_over_fifty, self.maria))

    def test_returning(self):
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.returning, self.john))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.returning, self.terry))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.returning, self.kate))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.returning, self.maria))

    def test_returning_and_test_age_twenty_and_us_or_age_over_fifty(self):
        self.assertFalse(
            self.json_expr.evaluate_boolean_expr(
                self.returning_and_age_twenty_and_us_or_age_over_fifty,
                self.john))
        self.assertFalse(
            self.json_expr.evaluate_boolean_expr(
                self.returning_and_age_twenty_and_us_or_age_over_fifty,
                self.terry))
        self.assertFalse(
            self.json_expr.evaluate_boolean_expr(
                self.returning_and_age_twenty_and_us_or_age_over_fifty,
                self.kate))
        self.assertTrue(
            self.json_expr.evaluate_boolean_expr(
                self.returning_and_age_twenty_and_us_or_age_over_fifty,
                self.maria))

    def test_not_returning_and_spanish(self):
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.not_returning_and_spanish, self.john))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.not_returning_and_spanish, self.terry))
        self.assertTrue(self.json_expr.evaluate_boolean_expr(
            self.not_returning_and_spanish, self.kate))
        self.assertFalse(self.json_expr.evaluate_boolean_expr(
            self.not_returning_and_spanish, self.maria))
