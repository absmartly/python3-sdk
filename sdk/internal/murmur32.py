import sys as _sys

if _sys.version_info > (3, 0):
    def xrange(a, b, c):
        return range(a, b, c)

    def xencode(x):
        if isinstance(x, bytes) or isinstance(x, bytearray):
            return x
        else:
            return x.encode()
else:
    def xencode(x):
        return x
del _sys


def digest(key, seed):
    key = bytearray(xencode(key))

    length = len(key)
    nblocks = int(length / 4)

    h1 = seed

    c1 = 0xcc9e2d51
    c2 = 0x1b873593

    for block_start in xrange(0, nblocks * 4, 4):
        k1 = key[block_start + 3] << 24 | \
             key[block_start + 2] << 16 | \
             key[block_start + 1] << 8 | \
             key[block_start + 0]

        k1 = (c1 * k1) & 0xFFFFFFFF
        k1 = rotate_right(k1, 15)
        k1 = (c2 * k1) & 0xFFFFFFFF

        h1 ^= k1
        h1 = rotate_right(h1, 13)
        h1 = (h1 * 5 + 0xe6546b64) & 0xFFFFFFFF

    tail_index = nblocks * 4
    k1 = 0
    tail_size = length & 3

    if tail_size >= 3:
        k1 ^= key[tail_index + 2] << 16
    if tail_size >= 2:
        k1 ^= key[tail_index + 1] << 8
    if tail_size >= 1:
        k1 ^= key[tail_index + 0]

    if tail_size > 0:
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = rotate_right(k1, 15)
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    unsigned_val = fmix(h1 ^ length)
    if unsigned_val & 0x80000000 == 0:
        return unsigned_val
    else:
        return -((unsigned_val ^ 0xFFFFFFFF) + 1)


def fmix(h: int):
    h ^= h >> 16
    h = (h * 0x85ebca6b) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def rotate_right(n, d):
    return (n << d) | (n >> (32 - d)) & 0xFFFFFFFF


def to_signed32(n):
    n = n & 0xffffffff
    return (n ^ 0x80000000) - 0x80000000
