import base64
import hashlib
from concurrent.futures import Future
from decimal import Decimal, ROUND_HALF_UP


def is_numeric(value) -> bool:
    # JS isNumeric is `typeof value === "number"`; bool is not a number.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_object(value) -> bool:
    # JS isObject accepts plain objects only, which map to dict here.
    return isinstance(value, dict)


def is_promise(value) -> bool:
    return isinstance(value, Future) or hasattr(value, '__await__')


def utf8_bytes(value: str) -> bytes:
    # Match the JS SDK (TextEncoder semantics): a lone surrogate becomes
    # U+FFFD instead of raising or being written as a CESU-8 sequence.
    try:
        return value.encode('utf-8')
    except UnicodeEncodeError:
        return value.encode('utf-16', 'surrogatepass') \
            .decode('utf-16', 'replace') \
            .encode('utf-8')


def base64_url_no_padding(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def unit_to_string(value) -> str:
    # A numeric UID is hashed as JS Number.prototype.toFixed(0) renders it:
    # rounded half away from zero, with no fractional part.
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if value != value:
        return "NaN"
    if value in (float('inf'), float('-inf')):
        return "Infinity" if value > 0 else "-Infinity"
    rounded = int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if rounded == 0 and (value < 0 or str(value).startswith('-')):
        return "-0"
    return str(rounded)


def hash_unit(value) -> str:
    digest = hashlib.md5(utf8_bytes(unit_to_string(value))).digest()
    return base64_url_no_padding(digest)
