import typing

from sdk.json.experiement_application import ExperimentApplication
from sdk.json.experiment_variant import ExperimentVariant


class Experiment:
    id: typing.Optional[int]
    name: typing.Optional[str]
    unit_type: typing.Optional[str]
    iteration: typing.Optional[int]
    seed_hi: typing.Optional[int]
    seed_lo: typing.Optional[int]
    split: typing.Optional[list[float]]
    traffic_seed_hi: typing.Optional[int]
    traffic_seed_lo: typing.Optional[int]
    traffic_split: typing.Optional[list[float]]
    full_on_variant: typing.Optional[int]
    applications: typing.Optional[list[ExperimentApplication]]
    variants: typing.Optional[list[ExperimentVariant]]
    audience_strict: typing.Optional[bool]
    audience: typing.Optional[str]
