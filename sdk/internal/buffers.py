
def put_uint32(buf: bytearray, offset: int, x: int):
    buf[offset] = x & 0xff
    buf[offset + 1] = (x >> 8) & 0xff
    buf[offset + 2] = (x >> 16) & 0xff
    buf[offset + 3] = (x >> 24) & 0xff


def get_uint32(buf: bytearray, offset: int):
    return (buf[offset] & 0xff) \
           | ((buf[offset + 1] & 0xff) << 8) \
           | ((buf[offset + 2] & 0xff) << 16) \
           | ((buf[offset + 3] & 0xff) << 24)


def get_uint24(buf: bytearray, offset: int):
    return (buf[offset] & 0xff) \
           | ((buf[offset + 1] & 0xff) << 8) \
           | ((buf[offset + 2] & 0xff) << 16)


def get_uint16(buf: bytearray, offset: int):
    return (buf[offset] & 0xff) \
           | ((buf[offset + 1] & 0xff) << 8)


def get_uint8(buf: bytearray, offset: int):
    return buf[offset] & 0xff
