# Port of the Collector's SwitchbackClusterKeys.normalize (via the Java SDK):
# the cluster key an attribute value yields, or None when it yields none. A
# non-empty str is the key as-is; an int is its base-10 text. bool is an int
# subclass in Python and is excluded, like every float (3.0 included), None,
# "", dict and list. The key is passed to the switchback assigner unhashed.


def normalize(value):
    if isinstance(value, str):
        return value if len(value) > 0 else None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(int(value))
    return None
