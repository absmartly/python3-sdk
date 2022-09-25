import base64
import hashlib
import threading

from sdk.internal import murmur32, buffers


class VariantAssigner:

    def __init__(self, unithash: bytearray):

        self.unitHash_ = murmur32.digest(unithash, 0)
        self.threadBuffer = threading.local()
        self.threadBuffer.value = bytearray(12)

    def assign(self, split: list, seed_hi: int, seed_lo: int):
        prob = self.probability(seed_hi, seed_lo)
        return self.choose_variant(split, prob)

    @staticmethod
    def choose_variant(split: list, prob: float):
        cum_sum = 0.0
        for index, item in enumerate(split):
            cum_sum += item
            if prob < cum_sum:
                return index

        return len(split) - 1

    def probability(self, seed_hi: int, seed_lo: int):
        buff = self.threadBuffer.value
        buffers.put_uint32(buff, 0, seed_lo)
        buffers.put_uint32(buff, 4, seed_hi)
        buffers.put_uint32(buff, 8, self.unitHash_)
        hashing = murmur32.digest(buff, 0)
        return (hashing & 0xffffffff) * VariantAssigner.__normalizer

    __normalizer = 1.0 / 0xffffffff




if __name__ == '__main__':
    has = hashlib.md5("bleh@absmartly.com".encode('utf-8'))
    dig = has.digest()
    res = base64.urlsafe_b64encode(dig).rstrip(b'=')
    variant = VariantAssigner(bytearray(res))
    res = variant.assign([0.5, 0.5], 0x00000000, 0x00000001)
    print(res)




