import unittest

from sdk.jsonexpr.expr_evaluator import ExprEvaluator
from sdk.jsonexpr.json_expr import JsonExpr


class ExprEvalTest(unittest.TestCase):
    json_expr = JsonExpr()

    def test_evaluate_considers_list_as_and_combinator(self):
        evaluator = ExprEvaluator(self.json_expr.operators, {})
        self.assertIsNotNone(evaluator.evaluate([{"value": True}, {"value": False}]))

    def test_evaluate_returns_null_if_operator_not_found(self):
        evaluator = ExprEvaluator(self.json_expr.operators, {})
        self.assertFalse(evaluator.evaluate({"not_found": True}))

    def test_evaluate_call_with_args(self):
        evaluator = ExprEvaluator(self.json_expr.operators, {})
        self.assertEqual([1, 2, 3], evaluator.evaluate({"value": [1, 2, 3]}))

    def test_bool_convert(self):
        evaluator = ExprEvaluator({}, {})
        self.assertTrue(evaluator.boolean_convert({}))
        self.assertTrue(evaluator.boolean_convert([]))
        self.assertFalse(evaluator.boolean_convert(None))

        self.assertTrue(evaluator.boolean_convert(True))
        self.assertTrue(evaluator.boolean_convert(1))
        self.assertTrue(evaluator.boolean_convert(2))
        self.assertTrue(evaluator.boolean_convert("abc"))
        self.assertTrue(evaluator.boolean_convert("1"))

        self.assertFalse(evaluator.boolean_convert(False))
        self.assertFalse(evaluator.boolean_convert(0))
        self.assertFalse(evaluator.boolean_convert(""))
        self.assertFalse(evaluator.boolean_convert("0"))
        self.assertFalse(evaluator.boolean_convert("False"))

    def test_number_convert(self):
        evaluator = ExprEvaluator({}, {})
        self.assertIsNone(evaluator.number_convert({}))
        self.assertIsNone(evaluator.number_convert([]))
        self.assertIsNone(evaluator.number_convert(None))
        self.assertIsNone(evaluator.number_convert(""))
        self.assertIsNone(evaluator.number_convert("abcd"))
        self.assertIsNone(evaluator.number_convert("x1234"))

        self.assertEqual(1.0, evaluator.number_convert(True))
        self.assertEqual(0.0, evaluator.number_convert(False))

        self.assertEqual(-1.0, evaluator.number_convert(-1.0))
        self.assertEqual(0.0, evaluator.number_convert(0.0))
        self.assertEqual(1.0, evaluator.number_convert(1.0))
        self.assertEqual(1.5, evaluator.number_convert(1.5))
        self.assertEqual(2.0, evaluator.number_convert(2.0))
        self.assertEqual(3.0, evaluator.number_convert(3.0))

        self.assertEqual(-1.0, evaluator.number_convert(-1))
        self.assertEqual(0.0, evaluator.number_convert(0))
        self.assertEqual(1.0, evaluator.number_convert(1))
        self.assertEqual(2.0, evaluator.number_convert(2))
        self.assertEqual(3.0, evaluator.number_convert(3))
        self.assertEqual(9007199254740991.0, evaluator.number_convert(9007199254740991))
        self.assertEqual(-9007199254740991.0, evaluator.number_convert(-9007199254740991))

        self.assertEqual(-1.0, evaluator.number_convert("-1"))
        self.assertEqual(0.0, evaluator.number_convert("0"))
        self.assertEqual(1.0, evaluator.number_convert("1"))
        self.assertEqual(1.5, evaluator.number_convert("1.5"))
        self.assertEqual(2.0, evaluator.number_convert("2"))
        self.assertEqual(3.0, evaluator.number_convert("3.0"))

    def test_string_convert(self):
        evaluator = ExprEvaluator({}, {})
        self.assertIsNone(evaluator.string_convert({}))
        self.assertIsNone(evaluator.string_convert([]))
        self.assertIsNone(evaluator.string_convert(None))

        self.assertEqual("True", evaluator.string_convert(True))
        self.assertEqual("False", evaluator.string_convert(False))

        self.assertEqual("", evaluator.string_convert(""))
        self.assertEqual("abc", evaluator.string_convert("abc"))

        self.assertEqual("-1.0", evaluator.string_convert(-1.0))
        self.assertEqual("0.0", evaluator.string_convert(0.0))
        self.assertEqual("1.0", evaluator.string_convert(1.0))
        self.assertEqual("1.5", evaluator.string_convert(1.5))
        self.assertEqual("2.0", evaluator.string_convert(2.0))
        self.assertEqual("3.0", evaluator.string_convert(3.0))
        self.assertEqual("2147483647.0", evaluator.string_convert(2147483647.0))
        self.assertEqual("-2147483647.0", evaluator.string_convert(-2147483647.0))
        self.assertEqual("9007199254740991.0", evaluator.string_convert(9007199254740991.0))
        self.assertEqual("-9007199254740991.0", evaluator.string_convert(-9007199254740991.0))
        self.assertEqual("0.9007199254740991", evaluator.string_convert(0.9007199254740991))
        self.assertEqual("-0.9007199254740991", evaluator.string_convert(-0.9007199254740991))

        self.assertEqual("-1", evaluator.string_convert(-1))
        self.assertEqual("0", evaluator.string_convert(0))
        self.assertEqual("1", evaluator.string_convert(1))
        self.assertEqual("2", evaluator.string_convert(2))
        self.assertEqual("3", evaluator.string_convert(3))
        self.assertEqual("2147483647", evaluator.string_convert(2147483647))
        self.assertEqual("-2147483647", evaluator.string_convert(-2147483647))
        self.assertEqual("9007199254740991", evaluator.string_convert(9007199254740991))
        self.assertEqual("-9007199254740991", evaluator.string_convert(-9007199254740991))

    def test_extract_var(self):
        vars = {
            "a": 1,
            "b": True,
            "c": False,
            "d": [1,2,3],
            "e": [1, {"z":2},3],
            "f": {"y": {"x": 3, "0": 10}}
        }

        evaluator = ExprEvaluator({}, vars)

        self.assertEqual(1, evaluator.extract_var("a"))
        self.assertEqual(True, evaluator.extract_var("b"))
        self.assertEqual(False, evaluator.extract_var("c"))
        self.assertEqual([1, 2, 3], evaluator.extract_var("d"))
        self.assertEqual([1, {"z": 2}, 3], evaluator.extract_var("e"))
        self.assertEqual({"y": {"x": 3, "0": 10}}, evaluator.extract_var("f"))

        self.assertIsNone(evaluator.extract_var("a/0"))
        self.assertIsNone(evaluator.extract_var("a/b"))
        self.assertIsNone(evaluator.extract_var("b/0"))
        self.assertIsNone(evaluator.extract_var("b/e"))

        self.assertEqual(1, evaluator.extract_var("d/0"))
        self.assertEqual(2, evaluator.extract_var("d/1"))
        self.assertEqual(3, evaluator.extract_var("d/2"))
        self.assertIsNone(evaluator.extract_var("d/3"))

        self.assertEqual(1, evaluator.extract_var("e/0"))
        self.assertEqual(2, evaluator.extract_var("e/1/z"))
        self.assertEqual(3, evaluator.extract_var("e/2"))
        self.assertIsNone(evaluator.extract_var("e/1/0"))

        self.assertEqual({"x": 3, "0": 10}, evaluator.extract_var("f/y"))
        self.assertEqual(3, evaluator.extract_var("f/y/x"))
        self.assertEqual(10, evaluator.extract_var("f/y/0"))

    def test_compare_null(self):
        evaluator = ExprEvaluator({}, {})

        self.assertEqual(0, evaluator.compare(None, None))

        self.assertIsNone(evaluator.compare(None, 0))
        self.assertIsNone(evaluator.compare(None, 1))
        self.assertIsNone(evaluator.compare(None, True))
        self.assertIsNone(evaluator.compare(None, False))
        self.assertIsNone(evaluator.compare(None, ""))
        self.assertIsNone(evaluator.compare(None, "abc"))
        self.assertIsNone(evaluator.compare(None, {}))
        self.assertIsNone(evaluator.compare(None, []))

    def test_compare_objects(self):
        evaluator = ExprEvaluator({}, {})
        
        self.assertIsNone(evaluator.compare({}, 0))
        self.assertIsNone(evaluator.compare({}, 1))
        self.assertIsNone(evaluator.compare({}, True))
        self.assertIsNone(evaluator.compare({}, False))
        self.assertIsNone(evaluator.compare({}, ""))
        self.assertIsNone(evaluator.compare({}, "abc"))
        self.assertEqual(0, evaluator.compare({}, {}))
        self.assertEqual(0, evaluator.compare({"a": 1}, {"a": 1}))
        self.assertIsNone(evaluator.compare({"a": 1}, {"b": 2}))
        self.assertIsNone(evaluator.compare({}, []))

        self.assertIsNone(evaluator.compare([], 0))
        self.assertIsNone(evaluator.compare([], 1))
        self.assertIsNone(evaluator.compare([], True))
        self.assertIsNone(evaluator.compare([], False))
        self.assertIsNone(evaluator.compare([], ""))
        self.assertIsNone(evaluator.compare([], "abc"))
        self.assertIsNone(evaluator.compare([], {}))
        self.assertEqual(0, evaluator.compare([], []))
        self.assertEqual(0, evaluator.compare([1, 2], [1, 2]))
        self.assertIsNone(evaluator.compare([1, 2], [3, 4]))

    def test_compare_booleans(self):
        evaluator = ExprEvaluator({}, {})

        self.assertEqual(0, evaluator.compare(False, 0))
        self.assertEqual(-1, evaluator.compare(False, 1))
        self.assertEqual(-1, evaluator.compare(False, True))
        self.assertEqual(0, evaluator.compare(False, False))
        self.assertEqual(0, evaluator.compare(False, ""))
        self.assertEqual(-1, evaluator.compare(False, "abc"))
        self.assertEqual(-1, evaluator.compare(False, {}))
        self.assertEqual(-1, evaluator.compare(False, []))

        self.assertEqual(1, evaluator.compare(True, 0))
        self.assertEqual(0, evaluator.compare(True, 1))
        self.assertEqual(0, evaluator.compare(True, True))
        self.assertEqual(1, evaluator.compare(True, False))
        self.assertEqual(1, evaluator.compare(True, ""))
        self.assertEqual(0, evaluator.compare(True, "abc"))
        self.assertEqual(0, evaluator.compare(True, {}))
        self.assertEqual(0, evaluator.compare(True, []))

    def test_compare_numbers(self):
        evaluator = ExprEvaluator({}, {})

        self.assertEqual(0, evaluator.compare(0, 0))
        self.assertEqual(-1, evaluator.compare(0, 1))
        self.assertEqual(-1, evaluator.compare(0, True))
        self.assertEqual(0, evaluator.compare(0, False))
        self.assertIsNone(evaluator.compare(0, ""))
        self.assertIsNone(evaluator.compare(0, "abc"))
        self.assertIsNone(evaluator.compare(0, {}))
        self.assertIsNone(evaluator.compare(0, []))

        self.assertEqual(1, evaluator.compare(1, 0))
        self.assertEqual(0, evaluator.compare(1, 1))
        self.assertEqual(0, evaluator.compare(1, True))
        self.assertEqual(1, evaluator.compare(1, False))
        self.assertIsNone(evaluator.compare(1, ""))
        self.assertIsNone(evaluator.compare(1, "abc"))
        self.assertIsNone(evaluator.compare(1, {}))
        self.assertIsNone(evaluator.compare(1, []))

        self.assertEqual(0, evaluator.compare(1.0, 1))
        self.assertEqual(1, evaluator.compare(1.5, 1))
        self.assertEqual(1, evaluator.compare(2.0, 1))
        self.assertEqual(1, evaluator.compare(3.0, 1))

        self.assertEqual(0, evaluator.compare(1, 1.0))
        self.assertEqual(-1, evaluator.compare(1, 1.5))
        self.assertEqual(-1, evaluator.compare(1, 2.0))
        self.assertEqual(-1, evaluator.compare(1, 3.0))

        self.assertEqual(0, evaluator.compare(9007199254740991, 9007199254740991))
        self.assertEqual(-1, evaluator.compare(0, 9007199254740991))
        self.assertEqual(1, evaluator.compare(9007199254740991, 0))

        self.assertEqual(0, evaluator.compare(9007199254740991.0, 9007199254740991.0))
        self.assertEqual(-1, evaluator.compare(0.0, 9007199254740991.0))
        self.assertEqual(1, evaluator.compare(9007199254740991.0, 0.0))

    def test_compare_strings(self):
        evaluator = ExprEvaluator({}, {})

        self.assertEqual(0, evaluator.compare("", ""))
        self.assertEqual(0, evaluator.compare("abc", "abc"))
        self.assertEqual(0, evaluator.compare("0", 0))
        self.assertEqual(0, evaluator.compare("1", 1))
        self.assertEqual(0, evaluator.compare("True", True))
        self.assertEqual(0, evaluator.compare("False", False))
        self.assertIsNone(evaluator.compare("", {}))
        self.assertIsNone(evaluator.compare("abc", {}))
        self.assertIsNone(evaluator.compare("", []))
        self.assertIsNone(evaluator.compare("abc", []))

        self.assertEqual(-1, evaluator.compare("abc", "bcd"))
        self.assertEqual(1, evaluator.compare("bcd", "abc"))
        self.assertEqual(-1, evaluator.compare("0", "1"))
        self.assertEqual(1, evaluator.compare("1", "0"))
        self.assertEqual(1, evaluator.compare("9", "100"))
        self.assertEqual(-1, evaluator.compare("100", "9"))
