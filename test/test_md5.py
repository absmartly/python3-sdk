import base64
import hashlib
import unittest


class MD5Test(unittest.TestCase):

    @staticmethod
    def md5_base64url(input_str):
        dig = hashlib.md5(input_str.encode('utf-8')).digest()
        return base64.urlsafe_b64encode(dig).rstrip(b'=').decode('ascii')

    def test_empty_string(self):
        self.assertEqual("1B2M2Y8AsgTpgAmY7PhCfg", self.md5_base64url(""))

    def test_single_space(self):
        self.assertEqual("chXunH2dwinSkhpA6JnsXw", self.md5_base64url(" "))

    def test_single_char_t(self):
        self.assertEqual("41jvpIn1gGLxDdcxa2Vkng", self.md5_base64url("t"))

    def test_two_chars_te(self):
        self.assertEqual("Vp73JkK-D63XEdakaNaO4Q", self.md5_base64url("te"))

    def test_three_chars_tes(self):
        self.assertEqual("KLZi2IO212_Zbk3cXpungA", self.md5_base64url("tes"))

    def test_four_chars_test(self):
        self.assertEqual("CY9rzUYh03PK3k6DJie09g", self.md5_base64url("test"))

    def test_five_chars_testy(self):
        self.assertEqual("K5I_V6RgP8c6sYKz-TVn8g", self.md5_base64url("testy"))

    def test_six_chars_testy1(self):
        self.assertEqual("8fT8xGipOhPkZ2DncKU-1A", self.md5_base64url("testy1"))

    def test_seven_chars_testy12(self):
        self.assertEqual("YqRAtOz000gIu61ErEH18A", self.md5_base64url("testy12"))

    def test_eight_chars_testy123(self):
        self.assertEqual("pfV2H07L6WvdqlY0zHuYIw", self.md5_base64url("testy123"))

    def test_special_characters(self):
        self.assertEqual(
            "4PIrO7lKtTxOcj2eMYlG7A",
            self.md5_base64url("special characters a\u00e7b\u2193c"))

    def test_quick_brown_fox(self):
        self.assertEqual(
            "nhB9nTcrtoJr2B01QqQZ1g",
            self.md5_base64url("The quick brown fox jumps over the lazy dog"))

    def test_quick_brown_fox_eats_pie(self):
        self.assertEqual(
            "iM-8ECRrLUQzixl436y96A",
            self.md5_base64url(
                "The quick brown fox jumps over the lazy dog and eats a pie"))

    def test_lorem_ipsum(self):
        self.assertEqual(
            "24m7XOq4f5wPzCqzbBicLA",
            self.md5_base64url(
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit, "
                "sed do eiusmod tempor incididunt ut labore et dolore magna "
                "aliqua. Ut enim ad minim veniam, quis nostrud exercitation "
                "ullamco laboris nisi ut aliquip ex ea commodo consequat. "
                "Duis aute irure dolor in reprehenderit in voluptate velit "
                "esse cillum dolore eu fugiat nulla pariatur. Excepteur sint "
                "occaecat cupidatat non proident, sunt in culpa qui officia "
                "deserunt mollit anim id est laborum."))
