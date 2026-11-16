import math
import re
from decimal import ROUND_HALF_UP, Context, Decimal


_NUMERIC = re.compile(r"[0-9]+")
_TRAILING_ZEROS = re.compile(r"\.?0{0,15}$")
_FIFTEEN_PLACES = Decimal(1).scaleb(-15)
# Below 1e21, 21 integer digits and 15 decimals fit exactly.
_FIXED = Context(prec=40, rounding=ROUND_HALF_UP)


def _number_to_string(value):
    # JS Evaluator.stringConvert: x.toFixed(15).replace(/\.?0{0,15}$/, "").
    # Numbers are doubles there, so ints out of range are +/-Infinity.
    try:
        value = float(value)
    except OverflowError:
        value = math.inf if value > 0 else -math.inf
    if math.isnan(value):
        text = "NaN"
    elif math.isinf(value):
        text = "Infinity" if value > 0 else "-Infinity"
    elif abs(value) >= 1e21:
        # toFixed falls back to ToString, the shortest round-trip form.
        text = repr(value)
    else:
        # toFixed rounds the exact binary value half up, and -0 prints "0".
        exact = Decimal(value if value != 0 else 0.0)
        text = format(exact.quantize(_FIFTEEN_PLACES, context=_FIXED), "f")
    return _TRAILING_ZEROS.sub("", text, count=1)


def _to_string(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return _number_to_string(value)
    return value if isinstance(value, str) else None


def parse_version(value):
    # Like the JavaScript SDK's parseSemver: a leading "v" and any build
    # metadata are dropped, and the core is split on "." without further
    # validation, so a non-numeric part (as in "abc") is compared as an
    # identifier rather than rejected.
    value = _to_string(value)
    if not value:
        return None
    if value[0] in "vV":
        value = value[1:]
    value = value.split("+", 1)[0]
    if not value:
        return None
    core, _, prerelease = value.partition("-")
    if not core:
        return None
    return core.split("."), prerelease


def _compare_identifiers(a, b):
    a_numeric = _NUMERIC.fullmatch(a) is not None
    b_numeric = _NUMERIC.fullmatch(b) is not None
    if a_numeric and b_numeric:
        a, b = a.lstrip("0") or "0", b.lstrip("0") or "0"
        if len(a) != len(b):
            return 1 if len(a) > len(b) else -1
    elif a_numeric:
        return -1
    elif b_numeric:
        return 1
    else:
        # JS compares strings by UTF-16 code unit.
        a, b = a.encode("utf-16-be"), b.encode("utf-16-be")
    return (a > b) - (a < b)


def compare_versions(lhs, rhs):
    left = parse_version(lhs)
    right = parse_version(rhs)
    if left is None or right is None:
        return None
    ln, rn = left[0], right[0]
    for i in range(max(len(ln), len(rn))):
        result = _compare_identifiers(ln[i] if i < len(ln) else "0",
                                      rn[i] if i < len(rn) else "0")
        if result != 0:
            return result
    lp, rp = left[1], right[1]
    if not lp and not rp:
        return 0
    if not lp:
        return 1
    if not rp:
        return -1
    lp, rp = lp.split("."), rp.split(".")
    for a, b in zip(lp, rp):
        result = _compare_identifiers(a, b)
        if result != 0:
            return result
    return (len(lp) > len(rp)) - (len(lp) < len(rp))
