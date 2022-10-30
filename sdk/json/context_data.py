import typing

from sdk.json.experiment import Experiment


class ContextData:
    experiments: typing.Optional[list[Experiment]] = None
