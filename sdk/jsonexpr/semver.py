import re
from decimal import Decimal, InvalidOperation


_VERSION = re.compile(r"^[0-9A-Za-z.-]+(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(value):
    if isinstance(value, bool):
        value = "true" if value else "false"
    elif isinstance(value, (int, float, Decimal)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value[:1].lower() == "v":
        value = value[1:]
    value = value.split("+", 1)[0]
    if not value or value.startswith("-") or value.endswith("-"):
        return None
    parts = value.split("-", 1)
    core = parts[0].split(".")
    if any(not p.isdigit() for p in core):
        return None
    numbers = tuple(int(p) for p in core)
    prerelease = ()
    if len(parts) == 2:
        if not parts[1]:
            return None
        prerelease = tuple(parts[1].split("."))
        if any(not p or not re.fullmatch(r"[0-9A-Za-z-]+", p) for p in prerelease):
            return None
    return numbers, prerelease


def compare_versions(lhs, rhs):
    left = parse_version(lhs)
    right = parse_version(rhs)
    if left is None or right is None:
        return None
    ln, rn = left[0], right[0]
    for i in range(max(len(ln), len(rn))):
        a = ln[i] if i < len(ln) else 0
        b = rn[i] if i < len(rn) else 0
        if a != b:
            return 1 if a > b else -1
    lp, rp = left[1], right[1]
    if not lp and not rp:
        return 0
    if not lp:
        return 1
    if not rp:
        return -1
    for a, b in zip(lp, rp):
        if a == b:
            continue
        an, bn = a.isdigit(), b.isdigit()
        if an and bn:
            return 1 if int(a) > int(b) else -1
        if an != bn:
            return -1 if an else 1
        return 1 if a > b else -1
    return (len(lp) > len(rp)) - (len(lp) < len(rp))
