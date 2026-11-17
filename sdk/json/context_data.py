import typing

from sdk.json.experiment import Experiment


class ContextData:
    experiments: typing.Optional[list[Experiment]] = None
    # A list of holdouts (sdk.json.holdout.Holdout objects or mappings with
    # the same keys). Left untyped so a malformed value only disables
    # holdouts instead of failing the whole context, as before this field
    # was read.
    holdouts: typing.Any = None
