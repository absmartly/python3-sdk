import json
import logging
from collections.abc import Mapping

import jsons

logger = logging.getLogger(__name__)

_MAX_DEPTH = 64
_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1


class SwitchbackAttributePath:
    """A switchback cluster attribute path, resolved like the Collector's
    SwitchbackAttributePath (via the Java SDK's port).

    "/" separates segments, a segment wrapped in ' or " is a literal key, and
    an unquoted segment that Guava Ints.tryParse accepts (ASCII digits, an
    optional leading '-') indexes a list and nothing else. Every other segment
    reads a mapping key. A path is malformed, and its experiment unservable,
    when a quote is left unterminated or any segment key, quoted or not,
    contains a '.' (dotted paths are not a nesting syntax).
    """
    __slots__ = ("keys", "indices")

    def __init__(self, keys, indices):
        self.keys = keys
        # Parallel to keys; None where the segment is a mapping key.
        self.indices = indices

    @staticmethod
    def parse_supported(path):
        """The parsed path, or None for an unsupported one: malformed (see
        above), empty, or an array index that is negative, first, last, or
        directly after another index. Analysis cannot read those."""
        if not isinstance(path, str):
            return None
        parsed = _parse(path)
        if parsed is None:
            return None
        n = len(parsed.keys)
        if n == 0:
            return None
        for i, index in enumerate(parsed.indices):
            if index is not None and (index < 0 or i == 0 or i == n - 1 or
                                      parsed.indices[i - 1] is not None):
                return None
        return parsed

    def root_key(self):
        """The attribute name the path starts at; a supported path always
        starts at a key segment."""
        return self.keys[0]

    def resolve(self, attributes):
        return self._resolve_from(attributes, 0)

    def resolve_attribute(self, root_value):
        """Resolves the path below root_key() in an attribute value, read as
        the Collector reads it: the value's JSON encoding as this SDK
        publishes it (jsons, nulls stripped), decoded into dict, list, str,
        bool, int or float. None when the value has no JSON encoding,
        contains a cycle, or nests containers deeper than 64."""
        if root_value is None:
            return None
        if type(root_value) in (str, bool, int):
            # Each of these decodes back to an equal value of the same type.
            decoded = root_value
        else:
            try:
                if not _acyclic_within_depth(root_value, set(), 0):
                    logger.warning(
                        "Switchback cluster attribute '%s' is cyclic or "
                        "nested deeper than %d", self.root_key(), _MAX_DEPTH)
                    return None
                decoded = json.loads(jsons.dumps(root_value,
                                                 strip_nulls=True))
            except Exception as e:
                logger.warning(
                    "Switchback cluster attribute '%s' cannot be encoded as "
                    "JSON: %s", self.root_key(), type(e).__name__)
                return None
        return self._resolve_from(decoded, 1)

    def _resolve_from(self, root, first):
        current = root
        for i in range(first, len(self.keys)):
            current = _step(current, self.keys[i], self.indices[i])
            if current is None:
                return None
        return current


def _parse(path):
    # A '.' anywhere, quoted or not, is unreadable: the Collector rejects any
    # parsed segment key containing '.'.
    if "." in path:
        return None
    keys = []
    indices = []
    i = 0
    length = len(path)
    while i < length:
        if path[i] == "/":
            i += 1
            continue
        first = path[i]
        if first in ("'", '"'):
            end = path.find(first, i + 1)
            if end < 0:
                return None
            keys.append(path[i + 1:end])
            indices.append(None)
            i = end + 1
        else:
            end = path.find("/", i)
            stop = length if end < 0 else end
            key = path[i:stop]
            keys.append(key)
            indices.append(try_parse_int(key))
            i = stop
    return SwitchbackAttributePath(tuple(keys), tuple(indices))


def _step(current, key, index):
    if index is not None:
        if isinstance(current, list):
            return current[index] if 0 <= index < len(current) else None
        return None
    if isinstance(current, Mapping):
        return current.get(key)
    return None


def _acyclic_within_depth(value, path, depth):
    # `path` holds the containers on the current branch only, so a value
    # shared by two siblings is not a cycle.
    if isinstance(value, Mapping):
        children = value.values()
    elif isinstance(value, (list, tuple, set, frozenset)):
        children = value
    else:
        return True
    if depth >= _MAX_DEPTH or id(value) in path:
        return False
    path.add(id(value))
    for child in children:
        if not _acyclic_within_depth(child, path, depth + 1):
            return False
    path.discard(id(value))
    return True


def try_parse_int(s):
    """Guava Ints.tryParse(String): an optional '-', then one or more ASCII
    digits, within int32 range; otherwise None. "+1" and non-ASCII digits
    are not numbers; "-0" is 0."""
    negative = s.startswith("-")
    digits = s[1:] if negative else s
    if not digits or any(c < "0" or c > "9" for c in digits):
        return None
    value = -int(digits) if negative else int(digits)
    if value < _INT32_MIN or value > _INT32_MAX:
        return None
    return value
