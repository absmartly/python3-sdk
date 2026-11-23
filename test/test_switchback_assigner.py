"""Switchback assigner and attribute paths, ported from the Java SDK's
SwitchbackAssignerGoldenVectorsTest and SwitchbackAttributePathTest
(java-sdk main, core-api/src/test/java/com/absmartly/sdk/internal/).

test/res/switchback/golden-vectors.json is copied byte-for-byte from
absmartly/abs 9bd2b5ca35 lib/utils/src/test/resources/switchback/
golden-vectors.json (git blob b314abeb9e97), and attribute-path-cases.json
from absmartly/abs 9bd2b5ca35 collector/src/test/resources/switchback/
attribute-path-cases.json (git blob 7b1d3fed5985), via the java-sdk copies.
"""
import hashlib
import json
import os
import unittest

from sdk.internal import buffers, murmur32, switchback_assigner
from sdk.internal import switchback_cluster_keys
from sdk.internal.switchback_attribute_path import (
    SwitchbackAttributePath, try_parse_int)

RESOURCES = os.path.join(os.path.dirname(__file__), "res", "switchback")
LONG_MIN = -(1 << 63)
LONG_MAX = (1 << 63) - 1


def read_resource(name):
    with open(os.path.join(RESOURCES, name), "rb") as f:
        return f.read()


def git_blob(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def cluster_unit(value):
    # The platform hashes a numeric cluster unit as its decimal text.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    assert isinstance(value, str), value
    return value


def exact_long(value):
    # 64-bit fields are decimal strings; a number would mean the fixture
    # regressed to a lossy encoding.
    assert isinstance(value, str), value
    return int(value)


class SwitchbackAssignerGoldenVectorsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads(read_resource("golden-vectors.json"))

    def test_fixtures_match_the_collector_blobs(self):
        self.assertEqual(
            "b314abeb9e97b35f911c7caacec90b8ff73b9d77",
            git_blob(read_resource("golden-vectors.json")))
        self.assertEqual(
            "7b1d3fed59856fcbc296ed68a820b43359ae1932",
            git_blob(read_resource("attribute-path-cases.json")))

    def test_assign_switchback_matches_every_golden_vector(self):
        cases = self.vectors["assignSwitchback"]
        self.assertEqual(882, len(cases))
        arm_counts = set()
        boundary_cases = 0
        for c in cases:
            period_index = exact_long(c["periodIndex"])
            seed = exact_long(c["seed"])
            arm_counts.add(c["armCount"])
            if period_index in (LONG_MIN, LONG_MAX) or \
                    seed in (LONG_MIN, LONG_MAX):
                boundary_cases += 1
            self.assertEqual(
                c["expectedVariant"],
                switchback_assigner.assign(cluster_unit(c["clusterUnit"]),
                                           period_index, seed,
                                           c["armCount"]), c)
        self.assertEqual({2, 3, 10}, arm_counts)
        self.assertGreater(boundary_cases, 0)

    def test_fisher_yates_permutation_matches_every_golden_vector(self):
        cases = self.vectors["fisherYatesPermutation"]
        self.assertEqual(504, len(cases))
        for c in cases:
            base = switchback_assigner.base_hash(
                cluster_unit(c["clusterUnit"]), exact_long(c["cycleIndex"]),
                exact_long(c["seed"]))
            self.assertEqual(
                c["expectedPermutation"],
                switchback_assigner.fisher_yates_permutation(c["armCount"],
                                                             base), c)

    def test_every_cycle_covers_every_arm_exactly_once(self):
        for arm_count in (2, 3, 10):
            for cycle in range(-3, 20):
                seen = [switchback_assigner.assign(
                    "store_42", cycle * arm_count + slot, 0x123456789abc,
                    arm_count) for slot in range(arm_count)]
                self.assertEqual(list(range(arm_count)), sorted(seen))

    def test_rejects_fewer_than_two_arms(self):
        for arm_count in (1, 0, -1, True, 2.0):
            with self.assertRaises(ValueError):
                switchback_assigner.assign("u", 0, 0, arm_count)
        with self.assertRaises(ValueError):
            switchback_assigner.fisher_yates_permutation(0, 0)

    def test_period_index_wraps_at_the_64_bit_bounds_like_java(self):
        # floorDiv/floorMod at Long.MIN_VALUE and Long.MAX_VALUE: the cycle
        # index the platform keys on, and the slot inside the cycle.
        for period_index, arm_count, cycle, slot in (
                (LONG_MIN, 3, -3074457345618258603, 1),
                (LONG_MAX, 10, 922337203685477580, 7),
                (-1, 2, -1, 1)):
            permutation = switchback_assigner.fisher_yates_permutation(
                arm_count, switchback_assigner.base_hash("market_1", cycle, 7))
            self.assertEqual(
                permutation[slot],
                switchback_assigner.assign("market_1", period_index, 7,
                                           arm_count))

    def test_seed_is_written_little_endian_low_word_first(self):
        # baseHash hashes le32(seed low word) ++ le32(seed high word) ++
        # le32(keyHash), as the platform's le64(seed) does. Pinned against
        # that byte layout built independently, and against golden vector
        # assign("market_1", 0, 1, 2) = 1, which flips to 0 with the words
        # swapped.
        key_hash = murmur32.digest("market_1\u001f0".encode(), 0)
        for seed in (1, 1 << 32, (1 << 32) | 0xfffffff9, -7,
                     LONG_MIN, LONG_MAX):
            layout = bytearray(12)
            buffers.put_uint32(layout, 0, seed & 0xffffffff)
            buffers.put_uint32(layout, 4, (seed >> 32) & 0xffffffff)
            buffers.put_uint32(layout, 8, key_hash)
            self.assertEqual(murmur32.digest(layout, 0),
                             switchback_assigner.base_hash("market_1", 0,
                                                           seed), seed)
        self.assertEqual(1, switchback_assigner.assign("market_1", 0, 1, 2))

    def test_lone_surrogates_are_encoded_like_java(self):
        # Java's Buffers.encodeUTF8 writes a lone surrogate as three bytes.
        self.assertEqual(b"\xed\xa0\x80",
                         switchback_assigner._utf8("\ud800"))
        self.assertEqual("\U0001F600".encode("utf-8"),
                         switchback_assigner._utf8("\U0001F600"))
        self.assertEqual(b"a\xf0\x9f\x98\x80\xed\xb0\x80",
                         switchback_assigner._utf8("a\U0001F600\udc00"))


class SwitchbackClusterKeysTest(unittest.TestCase):

    def test_strings_and_whole_integers_are_keys(self):
        self.assertEqual("Lisboa", switchback_cluster_keys.normalize("Lisboa"))
        self.assertEqual(" ", switchback_cluster_keys.normalize(" "))
        self.assertEqual("42", switchback_cluster_keys.normalize(42))
        self.assertEqual("-7", switchback_cluster_keys.normalize(-7))
        self.assertEqual("0", switchback_cluster_keys.normalize(0))
        self.assertEqual("123456789012345678901234567890",
                         switchback_cluster_keys.normalize(
                             123456789012345678901234567890))

    def test_every_other_value_has_no_key(self):
        # bool is an int subclass and 3.0 is a float: neither keys a cluster.
        for value in (None, "", True, False, 3.0, 1.5, -0.0, float("nan"),
                      float("inf"), {"a": 1}, [1], (1,), b"42"):
            self.assertIsNone(switchback_cluster_keys.normalize(value),
                              repr(value))

    def test_int_subclasses_are_keyed_by_their_value(self):
        import enum

        class Store(enum.IntEnum):
            LISBOA = 7

        self.assertEqual("7", switchback_cluster_keys.normalize(Store.LISBOA))


class SwitchbackAttributePathTest(unittest.TestCase):

    def test_matches_every_path_case(self):
        fixture = json.loads(read_resource("attribute-path-cases.json"))
        cases = fixture["cases"]
        self.assertEqual(7, len(cases))
        for c in cases:
            path = SwitchbackAttributePath.parse_supported(c["path"])
            if not c["supported"]:
                self.assertIsNone(path, c)
                continue
            self.assertIsNotNone(path, c)
            self.assertEqual(c["value"], path.resolve(fixture["attributes"]),
                             c)

    def test_quoted_segments_are_literal_keys(self):
        attributes = {"geo": {"0": "zero", "a/b": "slash"}}
        self.assertEqual("zero", SwitchbackAttributePath.parse_supported(
            "geo/'0'").resolve(attributes))
        self.assertEqual("slash", SwitchbackAttributePath.parse_supported(
            'geo/"a/b"').resolve(attributes))

    def test_rejects_malformed_paths(self):
        for path in ("geo/'0", "'geo", '"geo/city', 'geo/"', "geo.city",
                     "geo/a.b", "a./b", ".", "items/0.5/city", "'geo.city'",
                     '"geo.city"', "geo/'a.b'"):
            self.assertIsNone(SwitchbackAttributePath.parse_supported(path),
                              path)

    def test_separators_are_collapsed(self):
        attributes = {"geo": {"city": "Porto"}}
        self.assertEqual("Porto", SwitchbackAttributePath.parse_supported(
            "/geo//city/").resolve(attributes))
        self.assertEqual(attributes["geo"],
                         SwitchbackAttributePath.parse_supported(
                             "geo").resolve(attributes))

    def test_rejects_unsupported_paths(self):
        for path in (None, "", "/", "//", "0/city", "items/0",
                     "items/0/1/city", "items/-1/city", "'", 3, ["geo"]):
            self.assertIsNone(SwitchbackAttributePath.parse_supported(path),
                              repr(path))

    def test_index_segments_read_only_lists_and_key_segments_only_maps(self):
        attributes = {"items": [{"city": "Lisbon"}],
                      "geo": {"0": {"city": "zero"}},
                      "name": "scalar"}

        def resolve(path):
            return SwitchbackAttributePath.parse_supported(path).resolve(
                attributes)

        self.assertIsNone(resolve("geo/0/city"))
        self.assertIsNone(resolve("items/1/city"))
        self.assertIsNone(resolve("name/x"))
        self.assertIsNone(resolve("missing/x"))
        self.assertEqual("Lisbon", resolve("items/-0/city"))

    def test_cyclic_or_too_deep_values_have_no_key(self):
        path = SwitchbackAttributePath.parse_supported("geo/city")

        cyclic = {"city": "Porto"}
        cyclic["self"] = cyclic
        self.assertIsNone(path.resolve_attribute(cyclic))

        outer = {"city": "Porto"}
        outer["items"] = [(outer,)]
        self.assertIsNone(path.resolve_attribute(outer))

        # 65 nested maps: one past the depth bound.
        deep = {"leaf": "x"}
        for _ in range(64):
            deep = {"city": "Porto", "next": deep}
        self.assertIsNone(path.resolve_attribute(deep))
        self.assertEqual("Porto", path.resolve_attribute(deep["next"]))

        # A value reached twice through siblings is not a cycle.
        shared = {"a": "b"}
        self.assertEqual("Porto", path.resolve_attribute(
            {"city": "Porto", "x": shared, "y": shared}))

    def test_values_are_read_through_their_published_json_encoding(self):
        path = SwitchbackAttributePath.parse_supported("geo/city")
        # Tuples encode as arrays; a None entry in a map is stripped, as the
        # SDK publishes it; a whole float stays a float.
        self.assertEqual("Porto", SwitchbackAttributePath.parse_supported(
            "items/1/city").resolve_attribute(
                ({"city": "Lisbon"}, {"city": "Porto"})))
        self.assertIsNone(path.resolve_attribute({"city": None}))
        whole_float = path.resolve_attribute({"city": 3.0})
        self.assertIs(float, type(whole_float))
        self.assertIsNone(switchback_cluster_keys.normalize(whole_float))
        self.assertIs(int, type(path.resolve_attribute({"city": 3})))
        self.assertIsNone(path.resolve_attribute(None))
        self.assertEqual("x", SwitchbackAttributePath.parse_supported(
            "geo").resolve_attribute("x"))

    def test_try_parse_int_follows_guava(self):
        self.assertEqual(0, try_parse_int("0"))
        self.assertEqual(0, try_parse_int("-0"))
        self.assertEqual(7, try_parse_int("007"))
        self.assertEqual(2147483647, try_parse_int("2147483647"))
        self.assertEqual(-2147483648, try_parse_int("-2147483648"))
        self.assertEqual(7, try_parse_int("0" * 5000 + "7"))
        # Past CPython's default int() digit limit: out of range, no error.
        self.assertIsNone(try_parse_int("9" * 4301))
        self.assertIsNone(try_parse_int("-" + "9" * 10000))
        for s in ("", "-", "+1", "1a", " 1", "2147483648", "-2147483649",
                  "99999999999999999999", "٠", "1.0", "１"):
            self.assertIsNone(try_parse_int(s), s)


if __name__ == "__main__":
    unittest.main()
