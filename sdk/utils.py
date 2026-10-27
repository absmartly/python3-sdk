import base64
import hashlib
from concurrent.futures import Future


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
    # the exact value rounded half away from zero, "-" kept for negative
    # values that round to 0 (but not for -0 itself), and the plain number
    # string from 1e21 upwards. Integer arithmetic keeps this independent of
    # any Decimal context the caller has set.
    if isinstance(value, str):
        return value
    number = float(value)
    if number != number:
        return "NaN"
    if abs(number) >= 1e21:
        if number == float('inf'):
            return "Infinity"
        if number == float('-inf'):
            return "-Infinity"
        return repr(number)
    if isinstance(value, int):
        return str(value)
    numerator, denominator = abs(number).as_integer_ratio()
    quotient, remainder = divmod(numerator, denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return ("-" if number < 0 else "") + str(quotient)


def hash_unit(value) -> str:
    digest = hashlib.md5(utf8_bytes(unit_to_string(value))).digest()
    return base64_url_no_padding(digest)
