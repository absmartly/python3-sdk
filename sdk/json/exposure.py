import typing


class Exposure:
    id: typing.Optional[int] = 0
    name: typing.Optional[str] = None
    unit: typing.Optional[str] = None
    variant: typing.Optional[int] = 0
    exposedAt: typing.Optional[int] = 0
    assigned: typing.Optional[bool] = False
    eligible: typing.Optional[bool] = False
    overridden: typing.Optional[bool] = False
    fullOn: typing.Optional[bool] = False
    custom: typing.Optional[bool] = False
    audienceMismatch: typing.Optional[bool] = False
