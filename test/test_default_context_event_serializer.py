import unittest

from sdk.default_context_event_serializer import DefaultContextEventSerializer
from sdk.json.attribute import Attribute
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.publish_event import PublishEvent
from sdk.json.unit import Unit


class ContextDataDeserializerTest(unittest.TestCase):

    def test_serialize(self):
        event = PublishEvent()
        event.publishedAt = 123456789
        event.hashed = True
        goal1 = GoalAchievement()
        goal1.name = "goal1"
        goal1.achievedAt = 123456000
        goal1.properties = {
            "amount": 6,
            "value": 5.0,
            "tries": 1,
            "nested": {"value": 5},
            "nested_arr": {"nested": [1, 2, "test"]}
        }

        goal2 = GoalAchievement()
        goal2.name = "goal2"
        goal2.achievedAt = 123456789
        goal2.properties = None
        event.goals = [goal1, goal2]

        unit = Unit()
        unit.type = "session_id"
        unit.uid = "pAE3a1i5Drs5mKRNq56adA"

        unit2 = Unit()
        unit2.type = "user_id"
        unit2.uid = "JfnnlDI7RTiF9RgfG2JNCw"

        event.units = [unit, unit2]

        exposure = Exposure()
        exposure.id = 1
        exposure.name = "exp_test_ab"
        exposure.unit = "session_id"
        exposure.variant = 1
        exposure.exposedAt = 123470000
        exposure.assigned = True
        exposure.eligible = True
        exposure.overridden = False
        exposure.fullOn = False
        exposure.custom = False
        exposure.audienceMismatch = True

        attribute = Attribute()
        attribute.name = "attr1"
        attribute.value = "value1"
        attribute.setAt = 123456000

        attribute1 = Attribute()
        attribute1.name = "attr2"
        attribute1.value = "value2"
        attribute1.setAt = 123456789

        attribute2 = Attribute()
        attribute2.name = "attr2"
        attribute2.value = None
        attribute2.setAt = 123450000

        attribute3 = Attribute()
        attribute3.name = "attr3"
        attribute3.value = {"nested": {"value": 5}}
        attribute3.setAt = 123470000

        attribute4 = Attribute()
        attribute4.name = "attr4"
        attribute4.value = {"nested": {"nested": [1, 2, "test"]}}
        attribute4.setAt = 123480000

        event.attributes = [attribute,
                            attribute1,
                            attribute2,
                            attribute3,
                            attribute4]

        serializer = DefaultContextEventSerializer()
        result = serializer.serialize(event)
        self.assertTrue("pAE3a1i5Drs5mKRNq56adA" in str(result, "utf-8"))
