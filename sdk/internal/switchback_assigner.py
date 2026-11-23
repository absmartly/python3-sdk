import math

from sdk.internal import buffers, murmur32

# Balanced-block switchback assignment. Port of the Java SDK's
# SwitchbackAssigner (itself a port of the platform's SwitchbackAssignment,
# Guava murmur3_32_fixed, seed 0):
#   key       = utf8(clusterUnit + "\u001f" + cycleIndex)
#   baseHash  = murmur3_32(le64(seed) ++ le32(murmur3_32(key)))
#   stepHash  = murmur3_32(le32(baseHash) ++ le32(i)),  i = armCount-1 .. 1
#   j         = min(i, floor(u32(stepHash) / 0xffffffff * (i + 1)))
#   variant   = permutation[periodIndex mod armCount],
#               cycle = floor(periodIndex / armCount)
# periodIndex, cycleIndex and seed are signed 64-bit values; Python's // and
# % are already floor division and floor modulo. Any change here breaks parity
# with the platform golden vectors and the analysis-side schedule.

_NORMALIZER = 1.0 / 0xffffffff
_SEPARATOR = "\u001f"


def assign(cluster_unit: str, period_index: int, seed: int,
           arm_count: int) -> int:
    _require_valid_arm_count(arm_count)
    cycle_index = period_index // arm_count
    cycle_slot = period_index % arm_count
    return fisher_yates_permutation(
        arm_count, base_hash(cluster_unit, cycle_index, seed))[cycle_slot]


def base_hash(cluster_unit: str, cycle_index: int, seed: int) -> int:
    key_hash = murmur32.digest(
        _utf8(cluster_unit + _SEPARATOR + str(cycle_index)), 0)
    buffer = bytearray(12)
    buffers.put_uint32(buffer, 0, seed & 0xffffffff)
    buffers.put_uint32(buffer, 4, (seed >> 32) & 0xffffffff)
    buffers.put_uint32(buffer, 8, key_hash)
    return murmur32.digest(buffer, 0)


def fisher_yates_permutation(arm_count: int, base: int) -> list:
    _require_valid_arm_count(arm_count)
    permutation = list(range(arm_count))
    buffer = bytearray(8)
    buffers.put_uint32(buffer, 0, base)
    for i in range(arm_count - 1, 0, -1):
        buffers.put_uint32(buffer, 4, i)
        step_hash = murmur32.digest(buffer, 0)
        prob = (step_hash & 0xffffffff) * _NORMALIZER
        # prob == 1.0 would map to i + 1
        j = min(i, math.floor(prob * (i + 1)))
        permutation[i], permutation[j] = permutation[j], permutation[i]
    return permutation


def _utf8(value: str) -> bytes:
    # The Java SDK's Buffers.encodeUTF8: a surrogate pair is one 4-byte code
    # point and a lone surrogate is written as its own 3-byte sequence.
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-16", "surrogatepass") \
            .decode("utf-16", "surrogatepass") \
            .encode("utf-8", "surrogatepass")


def _require_valid_arm_count(arm_count: int):
    if isinstance(arm_count, bool) or not isinstance(arm_count, int) or \
            arm_count < 2:
        raise ValueError(f"armCount must be >= 2, got {arm_count}")
