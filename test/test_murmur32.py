import unittest
import sdk.internal.murmur32 as murmur


class Murmur32Test(unittest.TestCase):

    def _assert_hash(self, input_str, seed, expected_hex):
        key = bytearray(input_str.encode('utf-8'))
        actual = murmur.digest(key, seed)
        expected = murmur.to_signed32(expected_hex)
        self.assertEqual(expected, actual)

    def test_seed0_empty(self):
        self._assert_hash("", 0x00000000, 0x00000000)

    def test_seed0_space(self):
        self._assert_hash(" ", 0x00000000, 0x7ef49b98)

    def test_seed0_t(self):
        self._assert_hash("t", 0x00000000, 0xca87df4d)

    def test_seed0_te(self):
        self._assert_hash("te", 0x00000000, 0xedb8ee1b)

    def test_seed0_tes(self):
        self._assert_hash("tes", 0x00000000, 0x0bb90e5a)

    def test_seed0_test(self):
        self._assert_hash("test", 0x00000000, 0xba6bd213)

    def test_seed0_testy(self):
        self._assert_hash("testy", 0x00000000, 0x44af8342)

    def test_seed0_testy1(self):
        self._assert_hash("testy1", 0x00000000, 0x8a1a243a)

    def test_seed0_testy12(self):
        self._assert_hash("testy12", 0x00000000, 0x845461b9)

    def test_seed0_testy123(self):
        self._assert_hash("testy123", 0x00000000, 0x47628ac4)

    def test_seed0_special_characters(self):
        self._assert_hash("special characters a\u00e7b\u2193c", 0x00000000, 0xbe83b140)

    def test_seed0_quick_brown_fox(self):
        self._assert_hash(
            "The quick brown fox jumps over the lazy dog",
            0x00000000, 0x2e4ff723)

    def test_deadbeef_empty(self):
        self._assert_hash("", 0xdeadbeef, 0x0de5c6a9)

    def test_deadbeef_space(self):
        self._assert_hash(" ", 0xdeadbeef, 0x25acce43)

    def test_deadbeef_t(self):
        self._assert_hash("t", 0xdeadbeef, 0x3b15dcf8)

    def test_deadbeef_te(self):
        self._assert_hash("te", 0xdeadbeef, 0xac981332)

    def test_deadbeef_tes(self):
        self._assert_hash("tes", 0xdeadbeef, 0xc1c78dda)

    def test_deadbeef_test(self):
        self._assert_hash("test", 0xdeadbeef, 0xaa22d41a)

    def test_deadbeef_testy(self):
        self._assert_hash("testy", 0xdeadbeef, 0x84f5f623)

    def test_deadbeef_testy1(self):
        self._assert_hash("testy1", 0xdeadbeef, 0x09ed28e9)

    def test_deadbeef_testy12(self):
        self._assert_hash("testy12", 0xdeadbeef, 0x22467835)

    def test_deadbeef_testy123(self):
        self._assert_hash("testy123", 0xdeadbeef, 0xd633060d)

    def test_deadbeef_special_characters(self):
        self._assert_hash("special characters a\u00e7b\u2193c", 0xdeadbeef, 0xf7fdd8a2)

    def test_deadbeef_quick_brown_fox(self):
        self._assert_hash(
            "The quick brown fox jumps over the lazy dog",
            0xdeadbeef, 0x3a7b3f4d)

    def test_seed1_empty(self):
        self._assert_hash("", 0x00000001, 0x514e28b7)

    def test_seed1_space(self):
        self._assert_hash(" ", 0x00000001, 0x4f0f7132)

    def test_seed1_t(self):
        self._assert_hash("t", 0x00000001, 0x5db1831e)

    def test_seed1_te(self):
        self._assert_hash("te", 0x00000001, 0xd248bb2e)

    def test_seed1_tes(self):
        self._assert_hash("tes", 0x00000001, 0xd432eb74)

    def test_seed1_test(self):
        self._assert_hash("test", 0x00000001, 0x99c02ae2)

    def test_seed1_testy(self):
        self._assert_hash("testy", 0x00000001, 0xc5b2dc1e)

    def test_seed1_testy1(self):
        self._assert_hash("testy1", 0x00000001, 0x33925ceb)

    def test_seed1_testy12(self):
        self._assert_hash("testy12", 0x00000001, 0xd92c9f23)

    def test_seed1_testy123(self):
        self._assert_hash("testy123", 0x00000001, 0x3bc1712d)

    def test_seed1_special_characters(self):
        self._assert_hash("special characters a\u00e7b\u2193c", 0x00000001, 0x293327b5)

    def test_seed1_quick_brown_fox(self):
        self._assert_hash(
            "The quick brown fox jumps over the lazy dog",
            0x00000001, 0x78e69e27)
