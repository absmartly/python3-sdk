import typing

from sdk.json.custom_field_value import CustomFieldValue
from sdk.json.experiement_application import ExperimentApplication
from sdk.json.experiment_variant import ExperimentVariant


class Experiment:
    id: typing.Optional[int] = 0
    name: typing.Optional[str] = None
    unitType: typing.Optional[str] = None
    iteration: typing.Optional[int] = 0
    seedHi: typing.Optional[int] = 0
    seedLo: typing.Optional[int] = 0
    split: typing.Optional[list[float]] = None
    trafficSeedHi: typing.Optional[int] = 0
    trafficSeedLo: typing.Optional[int] = 0
    trafficSplit: typing.Optional[list[float]] = None
    fullOnVariant: typing.Optional[int] = 0
    applications: typing.Optional[list[ExperimentApplication]] = None
    variants: typing.Optional[list[ExperimentVariant]] = None
    audienceStrict: typing.Optional[bool] = False
    audience: typing.Optional[str] = None
    customFieldValues: typing.Optional[list[CustomFieldValue]] = None
    assignmentRules: typing.Optional[str] = None
    # The ids of the holdouts (in ContextData.holdouts) covering this
    # experiment. Untyped for the same reason as ContextData.holdouts: any
    # value other than a list of ids means "not covered".
    holdoutIds: typing.Any = None
    holdoutType: typing.Optional[str] = None
    # Switchback experiments (R33, cluster-defined). Untyped like holdoutIds,
    # so a malformed value only makes the experiment unservable instead of
    # failing the whole context. randomizationType "switchback" opts in;
    # absent or "unit" is a unit experiment, which ignores the other fields.
    # switchbackClusters maps a unit type to an attribute path in served
    # order; the order is semantic and kept as decoded.
    randomizationType: typing.Any = None
    switchbackClusters: typing.Any = None
    switchbackClusterValues: typing.Any = None
    switchbackStartAt: typing.Any = None
    switchbackPeriodMs: typing.Any = None
    switchbackCarryoverDurationMs: typing.Any = None
    switchbackBurnInDurationMs: typing.Any = None
    switchbackBurnOutDurationMs: typing.Any = None
    switchbackDesignType: typing.Any = None
    switchbackEstimand: typing.Any = None
