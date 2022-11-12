import unittest
import sdk.internal.buffers as buffers
import sdk.internal.murmur32 as murmur


class BuffersTest(unittest.TestCase):
    def test_put_uint32(self):
        bytes_len = 9
        i = 0
        while i < bytes_len - 3:
            byte = bytearray(bytes_len)

            expected = (i + 1) * 0xe6546b64
            expected = murmur.to_signed32(expected)
            buffers.put_uint32(byte, i, expected)
            actual = murmur.to_signed32(buffers.get_uint32(byte, i))
            self.assertEqual(expected, actual)

            b = 0
            while b < bytes_len:
                if b < i or b >= (i + 4):
                    self.assertEqual(0, byte[b])
                b += 1

            i += 1

    def test_get_uint32(self):
        byte = bytearray([97, 226, 134, 147, 98, 196, 0])
        i = 0
        while i < len(byte) - 3:
            self.assertEqual((byte[i] & 0xff) |
                             ((byte[i + 1] & 0xff) << 8) |
                             ((byte[i + 2] & 0xff) << 16) | (
                        (byte[i + 3] & 0xff) << 24),
                             buffers.get_uint32(byte, i))
            i += 1

    def test_get_uint24(self):
        byte = bytearray([97, 226, 134, 147, 98, 0])
        i = 0
        while i < len(byte) - 2:
            self.assertEqual((byte[i] & 0xff) |
                             ((byte[i + 1] & 0xff) << 8) |
                             ((byte[i + 2] & 0xff) << 16),
                             buffers.get_uint24(byte, i))
            i += 1

    def test_get_uint16(self):
        byte = bytearray([97, 226, 134, 147, 98, 0])
        i = 0
        while i < len(byte) - 1:
            self.assertEqual((byte[i] & 0xff) |
                             ((byte[i + 1] & 0xff) << 8),
                             buffers.get_uint16(byte, i))
            i += 1

    def test_get_uint8(self):
        byte = bytearray([97, 226, 134, 147, 98, 0])
        i = 0
        while i < len(byte):
            self.assertEqual((byte[i] & 0xff), buffers.get_uint8(byte, i))
            i += 1
