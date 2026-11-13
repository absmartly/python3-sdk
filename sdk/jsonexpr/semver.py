import re
from decimal import Decimal


_NUMERIC = re.compile(r"[0-9]+")


def _to_string(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
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
