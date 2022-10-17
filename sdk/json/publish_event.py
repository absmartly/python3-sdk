import typing

from sdk.json.attribute import Attribute
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.unit import Unit


class PublishEvent:
    hashed: typing.Optional[bool]
    units: typing.Optional[list[Unit]]
    published_at: typing.Optional[int]
    exposures: typing.Optional[list[Exposure]]
    goals: typing.Optional[list[GoalAchievement]]
    attributes: typing.Optional[list[Attribute]]
