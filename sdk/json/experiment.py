import typing

from sdk.json.experiement_application import ExperimentApplication
from sdk.json.experiment_variant import ExperimentVariant


class Experiment:
    id: typing.Optional[int] = 0
    name: typing.Optional[str] = None
    unit_type: typing.Optional[str] = None
    iteration: typing.Optional[int] = 0
    seed_hi: typing.Optional[int] = 0
    seed_lo: typing.Optional[int] = 0
    split: typing.Optional[list[float]] = None
    traffic_seed_hi: typing.Optional[int] = 0
    traffic_seed_lo: typing.Optional[int] = 0
    traffic_split: typing.Optional[list[float]] = None
    full_on_variant: typing.Optional[int] = 0
    applications: typing.Optional[list[ExperimentApplication]] = None
    variants: typing.Optional[list[ExperimentVariant]] = None
    audience_strict: typing.Optional[bool] = False
    audience: typing.Optional[str] = None
