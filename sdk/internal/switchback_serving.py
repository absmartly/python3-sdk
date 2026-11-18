from collections.abc import Mapping

from sdk.internal import switchback_cluster_keys
from sdk.internal.switchback_attribute_path import SwitchbackAttributePath

# Which unit serves a switchback experiment and under which cluster key. Port
# of the Java SDK's SwitchbackServing (the Collector's
# ContextAPI.switchbackServing, R33 cluster-defined switchbacks):
#
# - switchbackClusters, in its declared order (unit type id ascending), lists
#   the linked unit types and, for each, the attribute path of its cluster
#   value. The order is semantic: it is read in mapping order, never sorted.
# - No context unit of a linked type: the experiment does not apply (ABSENT).
# - Otherwise each linked unit, in source order, reads the attribute at its
#   source's path, normalised by switchback_cluster_keys. The first unit with
#   a value is the serving unit and the value is the cluster key; units
#   without one are skipped.
# - INELIGIBLE, served under the first linked unit: no unit has a value, two
#   units have different values, or an allow-list is set and lacks the key.
# - ELIGIBLE otherwise.
# - A missing, empty or unreadable cluster map takes the Collector's legacy
#   path instead (legacy()).

ABSENT = 0
INELIGIBLE = 1
ELIGIBLE = 2


class SwitchbackServing:
    __slots__ = ("status", "unit_type", "uid", "cluster_key")

    def __init__(self, status, unit_type=None, uid=None, cluster_key=None):
        self.status = status
        # The serving unit when ELIGIBLE, the first linked unit when
        # INELIGIBLE, None when ABSENT.
        self.unit_type = unit_type
        self.uid = uid
        # The raw normalised cluster key when ELIGIBLE; never hashed.
        self.cluster_key = cluster_key


def resolve(source_types, source_paths, allowed_values, units, read):
    """units maps unit type to uid (a context holds one uid per type), so
    the declared source order alone decides which unit serves. read(path)
    returns the attribute value at a SwitchbackAttributePath, or None."""
    first = None
    serving = None
    key = None
    disagreement = False
    for unit_type, path in zip(source_types, source_paths):
        uid = units.get(unit_type)
        if uid is None:
            continue
        if first is None:
            first = unit_type
        value = switchback_cluster_keys.normalize(read(path))
        if value is None:
            continue
        if key is None:
            key = value
            serving = unit_type
        elif key != value:
            disagreement = True

    if first is None:
        return SwitchbackServing(ABSENT)
    if key is None or disagreement or not allowed(allowed_values, key):
        return SwitchbackServing(INELIGIBLE, first, units[first])
    return SwitchbackServing(ELIGIBLE, serving, units[serving], key)


def legacy(unit_type, units):
    """The Collector's compatibility path for a missing, empty or unreadable
    cluster map: the declared unitType only identifies an ineligible control
    (never an assignment or a cluster); without a unit of that type the
    experiment does not apply."""
    if isinstance(unit_type, str) and units.get(unit_type) is not None:
        return SwitchbackServing(INELIGIBLE, unit_type, units[unit_type])
    return SwitchbackServing(ABSENT)


def allowed(allowed_values, key):
    # A None or empty allow-list admits every value, as in the Collector.
    if not allowed_values:
        return True
    return key in allowed_values


def allow_list(values):
    """switchbackClusterValues as a tuple of strings; None when unset or
    empty. Non-string entries can never equal a cluster key and are
    dropped, but a list holding only those still filters every value out."""
    if not isinstance(values, (list, tuple)) or len(values) == 0:
        return None
    return tuple(v for v in values if isinstance(v, str)) or ("",)


def sources(clusters):
    """The linked unit types and their parsed paths, in declared order; None
    for a missing, empty or non-mapping cluster map, a non-string unit type
    or any path that is not a supported attribute path."""
    if not isinstance(clusters, Mapping) or len(clusters) == 0:
        return None
    types = []
    paths = []
    for unit_type, path in clusters.items():
        if not isinstance(unit_type, str):
            return None
        parsed = SwitchbackAttributePath.parse_supported(path)
        if parsed is None:
            return None
        types.append(unit_type)
        paths.append(parsed)
    return tuple(types), tuple(paths)
