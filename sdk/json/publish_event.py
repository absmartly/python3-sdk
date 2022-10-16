from sdk.json.attribute import Attribute
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.unit import Unit


class PublishEvent:
    def __init__(self):
        self.hashed: bool
        self.units: list[Unit]
        self.published_at: int
        self.exposures: list[Exposure]
        self.goals: list[GoalAchievement]
        self.attributes: list[Attribute]
