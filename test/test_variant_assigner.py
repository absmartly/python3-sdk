import base64
import hashlib
import unittest

import sdk.internal.variant_assigner as assigner


def hash_unit(unit):
    dig = hashlib.md5(str(unit).encode('utf-8')).digest()  # noqa: S324
    return base64.urlsafe_b64encode(dig).rstrip(b'=')


class VariantAssignerChooseVariantTest(unittest.TestCase):

    def test_choose_variant_0_100_at_0(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.0, 1.0], 0.0))

    def test_choose_variant_0_100_at_50(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.0, 1.0], 0.5))

    def test_choose_variant_0_100_at_100(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.0, 1.0], 1.0))

    def test_choose_variant_100_0_at_0(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([1.0, 0.0], 0.0))

    def test_choose_variant_100_0_at_50(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([1.0, 0.0], 0.5))

    def test_choose_variant_100_0_at_100(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([1.0, 0.0], 1.0))

    def test_choose_variant_50_50_at_0(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([0.5, 0.5], 0.0))

    def test_choose_variant_50_50_at_25(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([0.5, 0.5], 0.25))

    def test_choose_variant_50_50_at_49(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([0.5, 0.5], 0.49999999))

    def test_choose_variant_50_50_at_50(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.5, 0.5], 0.5))

    def test_choose_variant_50_50_at_51(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.5, 0.5], 0.50000001))

    def test_choose_variant_50_50_at_75(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.5, 0.5], 0.75))

    def test_choose_variant_50_50_at_100(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.5, 0.5], 1.0))

    def test_choose_variant_333_at_0(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.0))

    def test_choose_variant_333_at_25(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.25))

    def test_choose_variant_333_at_332(self):
        self.assertEqual(0, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.33299999))

    def test_choose_variant_333_at_333(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.333))

    def test_choose_variant_333_at_334(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.33300001))

    def test_choose_variant_333_at_50(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.5))

    def test_choose_variant_333_at_665(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.66599999))

    def test_choose_variant_333_at_666(self):
        self.assertEqual(2, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.666))

    def test_choose_variant_333_at_667(self):
        self.assertEqual(2, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.66600001))

    def test_choose_variant_333_at_75(self):
        self.assertEqual(2, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 0.75))

    def test_choose_variant_333_at_100(self):
        self.assertEqual(2, assigner.VariantAssigner.choose_variant([0.333, 0.333, 0.334], 1.0))


class VariantAssignerEmailBinarySplitTest(unittest.TestCase):

    def setUp(self):
        self.assigner = assigner.VariantAssigner(bytearray(hash_unit("bleh@absmartly.com")))

    def test_email_binary_seed_0_0(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x00000000, 0x00000000))

    def test_email_binary_seed_0_1(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x00000000, 0x00000001))

    def test_email_binary_seed_pair1(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x8015406f, 0x7ef49b98))

    def test_email_binary_seed_pair2(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x3b2e7d90, 0xca87df4d))

    def test_email_binary_seed_pair3(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x52c1f657, 0xd248bb2e))

    def test_email_binary_seed_pair4(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x865a84d0, 0xaa22d41a))

    def test_email_binary_seed_pair5(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x27d1dc86, 0x845461b9))


class VariantAssignerEmailThreeWaySplitTest(unittest.TestCase):

    def setUp(self):
        self.assigner = assigner.VariantAssigner(bytearray(hash_unit("bleh@absmartly.com")))

    def test_email_three_way_seed_0_0(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x00000000, 0x00000000))

    def test_email_three_way_seed_0_1(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x00000000, 0x00000001))

    def test_email_three_way_seed_pair1(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x8015406f, 0x7ef49b98))

    def test_email_three_way_seed_pair2(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x3b2e7d90, 0xca87df4d))

    def test_email_three_way_seed_pair3(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x52c1f657, 0xd248bb2e))

    def test_email_three_way_seed_pair4(self):
        self.assertEqual(1, self.assigner.assign([0.33, 0.33, 0.34], 0x865a84d0, 0xaa22d41a))

    def test_email_three_way_seed_pair5(self):
        self.assertEqual(1, self.assigner.assign([0.33, 0.33, 0.34], 0x27d1dc86, 0x845461b9))


class VariantAssignerNumericBinarySplitTest(unittest.TestCase):

    def setUp(self):
        self.assigner = assigner.VariantAssigner(bytearray(hash_unit(123456789)))

    def test_numeric_binary_seed_0_0(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x00000000, 0x00000000))

    def test_numeric_binary_seed_0_1(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x00000000, 0x00000001))

    def test_numeric_binary_seed_pair1(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x8015406f, 0x7ef49b98))

    def test_numeric_binary_seed_pair2(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x3b2e7d90, 0xca87df4d))

    def test_numeric_binary_seed_pair3(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x52c1f657, 0xd248bb2e))

    def test_numeric_binary_seed_pair4(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x865a84d0, 0xaa22d41a))

    def test_numeric_binary_seed_pair5(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x27d1dc86, 0x845461b9))


class VariantAssignerNumericThreeWaySplitTest(unittest.TestCase):

    def setUp(self):
        self.assigner = assigner.VariantAssigner(bytearray(hash_unit(123456789)))

    def test_numeric_three_way_seed_0_0(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x00000000, 0x00000000))

    def test_numeric_three_way_seed_0_1(self):
        self.assertEqual(1, self.assigner.assign([0.33, 0.33, 0.34], 0x00000000, 0x00000001))

    def test_numeric_three_way_seed_pair1(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x8015406f, 0x7ef49b98))

    def test_numeric_three_way_seed_pair2(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x3b2e7d90, 0xca87df4d))

    def test_numeric_three_way_seed_pair3(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x52c1f657, 0xd248bb2e))

    def test_numeric_three_way_seed_pair4(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x865a84d0, 0xaa22d41a))

    def test_numeric_three_way_seed_pair5(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x27d1dc86, 0x845461b9))


class VariantAssignerHashBinarySplitTest(unittest.TestCase):

    def setUp(self):
        self.assigner = assigner.VariantAssigner(
            bytearray(hash_unit("e791e240fcd3df7d238cfc285f475e8152fcc0ec")))

    def test_hash_binary_seed_0_0(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x00000000, 0x00000000))

    def test_hash_binary_seed_0_1(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x00000000, 0x00000001))

    def test_hash_binary_seed_pair1(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x8015406f, 0x7ef49b98))

    def test_hash_binary_seed_pair2(self):
        self.assertEqual(1, self.assigner.assign([0.5, 0.5], 0x3b2e7d90, 0xca87df4d))

    def test_hash_binary_seed_pair3(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x52c1f657, 0xd248bb2e))

    def test_hash_binary_seed_pair4(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x865a84d0, 0xaa22d41a))

    def test_hash_binary_seed_pair5(self):
        self.assertEqual(0, self.assigner.assign([0.5, 0.5], 0x27d1dc86, 0x845461b9))


class VariantAssignerHashThreeWaySplitTest(unittest.TestCase):

    def setUp(self):
        self.assigner = assigner.VariantAssigner(
            bytearray(hash_unit("e791e240fcd3df7d238cfc285f475e8152fcc0ec")))

    def test_hash_three_way_seed_0_0(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x00000000, 0x00000000))

    def test_hash_three_way_seed_0_1(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x00000000, 0x00000001))

    def test_hash_three_way_seed_pair1(self):
        self.assertEqual(2, self.assigner.assign([0.33, 0.33, 0.34], 0x8015406f, 0x7ef49b98))

    def test_hash_three_way_seed_pair2(self):
        self.assertEqual(1, self.assigner.assign([0.33, 0.33, 0.34], 0x3b2e7d90, 0xca87df4d))

    def test_hash_three_way_seed_pair3(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x52c1f657, 0xd248bb2e))

    def test_hash_three_way_seed_pair4(self):
        self.assertEqual(0, self.assigner.assign([0.33, 0.33, 0.34], 0x865a84d0, 0xaa22d41a))

    def test_hash_three_way_seed_pair5(self):
        self.assertEqual(1, self.assigner.assign([0.33, 0.33, 0.34], 0x27d1dc86, 0x845461b9))
