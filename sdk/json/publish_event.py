import typing

from sdk.json.attribute import Attribute
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.unit import Unit


class PublishEvent:
    hashed: typing.Optional[bool] = False
    units: typing.Optional[list[Unit]] = None
    publishedAt: typing.Optional[int] = 0
    exposures: typing.Optional[list[Exposure]] = None
    goals: typing.Optional[list[GoalAchievement]] = None
    attributes: typing.Optional[list[Attribute]] = None
