import base64
import hashlib
import unittest

import sdk.internal.variant_assigner as assigner


class VariantAssignerTest(unittest.TestCase):
    def test_choose_variant(self):
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.0, 1.0], 0.0))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.0, 1.0], 0.5))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.0, 1.0], 1.0))

        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [1.0, 0.0], 0.0))
        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [1.0, 0.0], 0.5))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [1.0, 0.0], 1.0))

        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 0.0))
        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 0.25))
        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 0.49999999))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 0.5))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 0.50000001))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 0.75))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.5, 0.5], 1.0))

        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.0))
        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.25))
        self.assertEqual(0, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.33299999))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.333))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.33300001))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.5))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.66599999))
        self.assertEqual(2, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.666))
        self.assertEqual(2, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.66600001))
        self.assertEqual(2, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 0.75))
        self.assertEqual(2, assigner.VariantAssigner.choose_variant(
            [0.333, 0.333, 0.334], 1.0))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.0, 1.0], 0.0))
        self.assertEqual(1, assigner.VariantAssigner.choose_variant(
            [0.0, 1.0], 1.0))

    def test_assignments_match(self):
        splits = [[0.5, 0.5],
                  [0.5, 0.5],
                  [0.5, 0.5],
                  [0.5, 0.5],
                  [0.5, 0.5],
                  [0.5, 0.5],
                  [0.5, 0.5],
                  [0.33, 0.33, 0.34],
                  [0.33, 0.33, 0.34],
                  [0.33, 0.33, 0.34],
                  [0.33, 0.33, 0.34],
                  [0.33, 0.33, 0.34],
                  [0.33, 0.33, 0.34],
                  [0.33, 0.33, 0.34]]

        seeds = [[0x00000000, 0x00000000],
                 [0x00000000, 0x00000001],
                 [0x8015406f, 0x7ef49b98],
                 [0x3b2e7d90, 0xca87df4d],
                 [0x52c1f657, 0xd248bb2e],
                 [0x865a84d0, 0xaa22d41a],
                 [0x27d1dc86, 0x845461b9],
                 [0x00000000, 0x00000000],
                 [0x00000000, 0x00000001],
                 [0x8015406f, 0x7ef49b98],
                 [0x3b2e7d90, 0xca87df4d],
                 [0x52c1f657, 0xd248bb2e],
                 [0x865a84d0, 0xaa22d41a],
                 [0x27d1dc86, 0x845461b9]]

        unituid = "bleh@absmartly.com"
        dig = hashlib.md5(unituid.encode('utf-8')).digest()
        unithash = base64.urlsafe_b64encode(dig).rstrip(b'=')
        var_assigner = assigner.VariantAssigner(bytearray(unithash))
        expected_variants = [0, 1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 0, 1, 1]

        self.assert_variants(seeds, splits, expected_variants, var_assigner)

        unituid = str(123456789)
        dig = hashlib.md5(unituid.encode('utf-8')).digest()
        unithash = base64.urlsafe_b64encode(dig).rstrip(b'=')
        var_assigner = assigner.VariantAssigner(bytearray(unithash))
        expected_variants = [1, 0, 1, 1, 1, 0, 0, 2, 1, 2, 2, 2, 0, 0]

        self.assert_variants(seeds, splits, expected_variants, var_assigner)

        unituid = "e791e240fcd3df7d238cfc285f475e8152fcc0ec"
        dig = hashlib.md5(unituid.encode('utf-8')).digest()
        unithash = base64.urlsafe_b64encode(dig).rstrip(b'=')
        var_assigner = assigner.VariantAssigner(bytearray(unithash))
        expected_variants = [1, 0, 1, 1, 0, 0, 0, 2, 0, 2, 1, 0, 0, 1]

        self.assert_variants(seeds, splits, expected_variants, var_assigner)

    def assert_variants(self, seeds, splits, expected_variants, var_assigner):
        for index, seed in enumerate(seeds):
            frags = seed
            split = splits[index]
            variant = var_assigner.assign(split, frags[0], frags[1])
            self.assertEqual(expected_variants[index], variant)
