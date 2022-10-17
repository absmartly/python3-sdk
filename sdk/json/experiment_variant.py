import typing
from dataclasses import dataclass


class ExperimentVariant:
    name: typing.Optional[str]
    config: typing.Optional[str]
