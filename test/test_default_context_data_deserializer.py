import os
import unittest

from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.json.context_data import ContextData
from sdk.json.experiement_application import ExperimentApplication
from sdk.json.experiment import Experiment
from sdk.json.experiment_variant import ExperimentVariant


class ContextDataDeserializerTest(unittest.TestCase):

    def test_deserialize(self):
        with open(os.path.join(
                os.path.dirname(__file__),
                'res/context.json'),
                'r') as file:
            data = file.read()
        deser = DefaultContextDataDeserializer()
        result = deser.deserialize(bytes(data, encoding="utf-8"), 0, len(data))
        exp_appl = ExperimentApplication()
        exp_appl.name = "website"

        varone = ExperimentVariant()
        varone.name = "A"
        varone.config = None
        vartwo = ExperimentVariant()
        vartwo.name = "0"
        vartwo.config = "{\"banner.border\":1,\"banner.size\":\"large\"}"

        experiment0 = Experiment()
        experiment0.id = 1
        experiment0.name = "exp_test_ab"
        experiment0.unitType = "session_id"
        experiment0.iteration = 1
        experiment0.seedHi = 3603515
        experiment0.seedLo = 233373850
        experiment0.split = [0.5, 0.5]
        experiment0.trafficSeedHi = 449867249
        experiment0.trafficSeedLo = 455443629
        experiment0.trafficSplit = [0.0, 1.0]
        experiment0.fullOnVariant = 0
        experiment0.applications = [exp_appl]
        experiment0.variants = [
            varone,
            vartwo
        ]
        experiment0.audienceStrict = False
        experiment0.audience = None

        vartwot = ExperimentVariant()
        vartwot.name = "0"
        vartwot.config = "{\"button.color\":\"blue\"}"

        vartwott = ExperimentVariant()
        vartwott.name = "C"
        vartwott.config = "{\"button.color\":\"red\"}"

        experiment1 = Experiment()
        experiment1.id = 2
        experiment1.name = "exp_test_abc"
        experiment1.unitType = "session_id"
        experiment1.iteration = 1
        experiment1.seedHi = 55006150
        experiment1.seedLo = 47189152
        experiment1.split = [0.34, 0.33, 0.33]
        experiment1.trafficSeedHi = 705671872
        experiment1.trafficSeedLo = 212903484
        experiment1.trafficSplit = [0.0, 1.0]
        experiment1.fullOnVariant = 0
        experiment1.applications = [exp_appl]
        experiment1.variants = [
            varone,
            vartwot,
            vartwott
        ]
        experiment1.audienceStrict = False
        experiment1.audience = ""

        vartwotta = ExperimentVariant()
        vartwotta.name = "B"
        vartwotta.config = "{\"card.width\":\"80%\"}"
        vartwottaa = ExperimentVariant()
        vartwottaa.name = "C"
        vartwottaa.config = "{\"card.width\":\"75%\"}"

        experiment2 = Experiment()
        experiment2.id = 3
        experiment2.name = "exp_test_not_eligible"
        experiment2.unitType = "user_id"
        experiment2.iteration = 1
        experiment2.seedHi = 503266407
        experiment2.seedLo = 144942754
        experiment2.split = [0.34, 0.33, 0.33]
        experiment2.trafficSeedHi = 87768905
        experiment2.trafficSeedLo = 511357582
        experiment2.trafficSplit = [0.99, 0.01]
        experiment2.fullOnVariant = 0
        experiment2.applications = [exp_appl]
        experiment2.variants = [
            varone,
            vartwotta,
            vartwottaa
        ]
        experiment2.audienceStrict = False
        experiment2.audience = "{}"

        vartwottab = ExperimentVariant()
        vartwottab.name = "B"
        vartwottab.config = \
            "{\"submit.color\":\"red\",\"submit.shape\":\"circle\"}"

        vartwottabc = ExperimentVariant()
        vartwottabc.name = "C"
        vartwottabc.config = \
            "{\"submit.color\":\"blue\",\"submit.shape\":\"rect\"}"

        vartwottabb = ExperimentVariant()
        vartwottabb.name = "D"
        vartwottabb.config = \
            "{\"submit.color\":\"green\",\"submit.shape\":\"square\"}"

        experiment3 = Experiment()
        experiment3.id = 4
        experiment3.name = "exp_test_fullon"
        experiment3.unitType = "session_id"
        experiment3.iteration = 1
        experiment3.seedHi = 856061641
        experiment3.seedLo = 990838475
        experiment3.split = [0.25, 0.25, 0.25, 0.25]
        experiment3.seedHi = 856061641
        experiment3.seedLo = 990838475
        experiment3.trafficSplit = [0.0, 1.0]
        experiment3.fullOnVariant = 2
        experiment3.applications = [exp_appl]
        experiment3.variants = [
            varone,
            vartwottab,
            vartwottabc,
            vartwottabb
        ]
        experiment3.audienceStrict = False
        experiment3.audience = "null"

        expected = ContextData()
        expected.experiments = [experiment0,
                                experiment1,
                                experiment2,
                                experiment3]

        self.assertIsNotNone(result)
        self.assertEqual(len(result.experiments),
                         len(expected.experiments))
        self.assertEqual(result.experiments[3].variants[3].config,
                         expected.experiments[3].variants[3].config)
