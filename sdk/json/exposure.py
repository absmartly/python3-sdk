import typing


class Exposure:
    id: typing.Optional[int] = 0
    name: typing.Optional[str] = None
    unit: typing.Optional[str] = None
    variant: typing.Optional[int] = 0
    exposed_at: typing.Optional[int] = 0
    assigned: typing.Optional[bool] = False
    eligible: typing.Optional[bool] = False
    overridden: typing.Optional[bool] = False
    full_on: typing.Optional[bool] = False
    custom: typing.Optional[bool] = False
    audience_mismatch: typing.Optional[bool] = False
