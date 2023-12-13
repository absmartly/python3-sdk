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
