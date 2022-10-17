import typing


class Exposure:
    id: typing.Optional[int]
    name: typing.Optional[str]
    unit: typing.Optional[str]
    variant: typing.Optional[int]
    exposed_at: typing.Optional[int]
    assigned: typing.Optional[bool]
    eligible: typing.Optional[bool]
    overridden: typing.Optional[bool]
    full_on: typing.Optional[bool]
    custom: typing.Optional[bool]
    audience_mismatch: typing.Optional[bool]
