import json
import unittest
from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.absmartly import ABsmartly
from sdk.absmartly_config import ABsmartlyConfig
from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_context_event_serializer import \
    DefaultContextEventSerializer
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.json.publish_event import PublishEvent
from sdk.time.fixed_clock import FixedClock


class ClientContextMock(Client):
    def __init__(self, config, http_client):
        super().__init__(config, http_client)
        self._publish_calls = []
        self._refresh_data = None

    def get_context_data(self):
        future = Future()
        if self._refresh_data is not None:
            future.set_result(self._refresh_data)
        else:
            data = ContextData()
            data.experiments = []
            future.set_result(data)
        return future

    def publish(self, event: PublishEvent):
        self._publish_calls.append(event)
        future = Future()
        future.set_result(None)
        return future


class SystemAttributesTest(unittest.TestCase):
    """Tests for §4 of the brief: audiences and assignment-rule conditions
    always evaluate with the configured application and environment, user
    attributes override them, app_version is gone, and nothing extra is
    published. The reference implementation is the JavaScript SDK.
    """

    units = {
        "session_id": "e791e240fcd3df7d238cfc285f475e8152fcc0ec",
        "user_id": "123456789",
        "email": "bleh@absmartly.com",
    }

    deser = DefaultContextDataDeserializer()
    audeser = DefaultAudienceDeserializer()
    serializer = DefaultContextEventSerializer()

    def set_up(self, application="website", environment="production"):
        self.clock = FixedClock(1_620_000_000_000)
        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.api_key = "gfsgsgsf"
        client_config.application = application
        client_config.environment = environment
        http_config = DefaultHTTPClientConfig()
        http_client = DefaultHTTPClient(http_config)
        self.client = ClientContextMock(client_config, http_client)
        self.application = application
        self.environment = environment
        self.data_provider = DefaultContextDataProvider(self.client)
        self.event_handler = DefaultContextEventHandler(self.client)
        self.variable_parser = DefaultVariableParser()
        self.audience_matcher = AudienceMatcher(self.audeser)

    def strict_audience_data(self, filter_list):
        """A single strict experiment, 0/100 split to variant 1 (B), whose
        audience is the given filter. Matches the JS reference's
        strictAudienceResponse."""
        experiment = {
            "id": 1,
            "name": "exp_test_ab",
            "iteration": 1,
            "unitType": "session_id",
            "seedHi": 3603515,
            "seedLo": 233373850,
            "split": [0.0, 1.0],
            "trafficSeedHi": 449867249,
            "trafficSeedLo": 455443629,
            "trafficSplit": [0.0, 1.0],
            "fullOnVariant": 0,
            "applications": [{"name": "website"}],
            "variants": [
                {"name": "A", "config": None},
                {"name": "B",
                 "config": "{\"banner.border\":1,\"banner.size\":\"large\"}"},
            ],
            "audienceStrict": True,
            "audience": json.dumps({"filter": filter_list}),
        }
        content = json.dumps({"experiments": [experiment]})
        return self.deser.deserialize(
            bytes(content, encoding="utf-8"), 0, len(content))

    def environment_is(self, value):
        return [{"eq": [{"var": "environment"}, {"value": value}]}]

    def application_is(self, value):
        return [{"eq": [{"var": "application"}, {"value": value}]}]

    def create_context(self, data):
        config = ContextConfig()
        config.units = dict(self.units)
        data_future = Future()
        data_future.set_result(data)
        return Context(
            self.clock, config, data_future,
            self.data_provider, self.event_handler, None,
            self.variable_parser, self.audience_matcher,
            self.application, self.environment)

    def exposure_of(self, context, name):
        for exposure in context.exposures:
            if exposure.name == name:
                return exposure
        return None

    # §4.1
    def test_strict_audience_on_environment_matches(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("production")))
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        self.assertFalse(self.exposure_of(context, "exp_test_ab")
                         .audienceMismatch)
        self.assertEqual(
            "large", context.get_variable_value("banner.size", "default"))
        context.close()

    # §4.2
    def test_strict_audience_on_application_matches(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.application_is("website")))
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        self.assertFalse(self.exposure_of(context, "exp_test_ab")
                         .audienceMismatch)
        context.close()

    # §4.3
    def test_strict_audience_on_other_environment_gives_variant_0(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("staging")))
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertTrue(self.exposure_of(context, "exp_test_ab")
                        .audienceMismatch)
        context.close()

    def test_strict_audience_on_other_application_gives_variant_0(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.application_is("mobile")))
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertTrue(self.exposure_of(context, "exp_test_ab")
                        .audienceMismatch)
        context.close()

    # Full-on experiments match the configured environment.
    def test_full_on_matches_configured_environment(self):
        self.set_up()
        data = self.strict_audience_data(self.environment_is("production"))
        data.experiments[0].fullOnVariant = 1
        data.experiments[0].split = [0.5, 0.5]
        context = self.create_context(data)
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        exposure = self.exposure_of(context, "exp_test_ab")
        self.assertFalse(exposure.audienceMismatch)
        self.assertTrue(exposure.fullOn)
        context.close()

    # §4.4
    def test_user_set_environment_wins_set_after_creation(self):
        self.set_up()
        staging = self.create_context(
            self.strict_audience_data(self.environment_is("staging")))
        staging.set_attribute("environment", "staging")
        self.assertEqual(1, staging.get_treatment("exp_test_ab"))
        staging.close()

        production = self.create_context(
            self.strict_audience_data(self.environment_is("production")))
        production.set_attribute("environment", "staging")
        self.assertEqual(0, production.get_treatment("exp_test_ab"))
        self.assertTrue(self.exposure_of(production, "exp_test_ab")
                        .audienceMismatch)
        production.close()

    # §4.4
    def test_cached_assignment_invalidated_when_attribute_set_later(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("staging")))
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))

        context.set_attribute("environment", "staging")
        self.assertEqual(1, context.peek_treatment("exp_test_ab"))
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        self.assertFalse(self.exposure_of(context, "exp_test_ab")
                         .audienceMismatch)
        context.close()

    def test_matching_assignment_invalidated_when_user_overrides(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("production")))
        self.assertEqual(1, context.peek_treatment("exp_test_ab"))

        context.set_attribute("environment", "staging")
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertTrue(self.exposure_of(context, "exp_test_ab")
                        .audienceMismatch)
        context.close()

    def test_user_set_application_wins(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.application_is("mobile")))
        context.set_attribute("application", "mobile")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        context.close()

    # §4.6
    def test_missing_environment_config_leaves_key_out(self):
        for environment in (None, ""):
            with self.subTest(environment=environment):
                self.set_up(environment=environment)
                matching = self.create_context(
                    self.strict_audience_data(
                        self.environment_is("production")))
                self.assertEqual(0, matching.get_treatment("exp_test_ab"))
                self.assertTrue(self.exposure_of(matching, "exp_test_ab")
                                .audienceMismatch)
                self.assertNotIn(
                    "environment", matching._build_audience_attributes())
                self.assertEqual(
                    {"application": "website"},
                    matching._build_audience_attributes())
                matching.close()

    def test_missing_application_config_leaves_key_out(self):
        self.set_up(application="")
        context = self.create_context(
            self.strict_audience_data(self.application_is("website")))
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertEqual(
            {"environment": "production"},
            context._build_audience_attributes())
        context.close()

    # §4.8
    def test_app_version_not_exposed_to_audiences(self):
        self.set_up()
        # The client always sends X-Application-Version, so "configured".
        context = self.create_context(
            self.strict_audience_data(
                [{"eq": [{"var": "app_version"}, {"value": "0"}]}]))
        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertTrue(self.exposure_of(context, "exp_test_ab")
                        .audienceMismatch)
        attrs = context._build_audience_attributes()
        self.assertNotIn("app_version", attrs)
        self.assertEqual(
            {"application": "website", "environment": "production"}, attrs)
        context.close()

    def test_user_set_app_version_still_evaluated(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(
                [{"eq": [{"var": "app_version"}, {"value": "1.2.3"}]}]))
        context.set_attribute("app_version", "1.2.3")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        context.close()

    # §4
    def test_system_attributes_not_reported_as_user_attributes(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("production")))
        context.set_attribute("age", 25)
        self.assertEqual({"age": 25}, context.get_attributes())
        self.assertIsNone(context.get_attribute("environment"))
        self.assertIsNone(context.get_attribute("application"))
        context.close()

    # §4.7
    def test_nothing_extra_published(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("production")))
        context.set_attribute("custom_attr", "custom_value")
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        context.publish()

        self.assertEqual(1, len(self.client._publish_calls))
        event = self.client._publish_calls[0]
        payload = json.loads(bytes(self.serializer.serialize(event)))
        names = [attr["name"] for attr in payload.get("attributes", [])]
        self.assertEqual(["custom_attr"], names)
        self.assertNotIn("application", names)
        self.assertNotIn("environment", names)
        self.assertNotIn("app_version", names)
        context.close()

    def test_publish_payload_has_no_attributes_when_none_set(self):
        self.set_up()
        context = self.create_context(
            self.strict_audience_data(self.environment_is("production")))
        self.assertEqual(1, context.get_treatment("exp_test_ab"))
        context.publish()
        event = self.client._publish_calls[0]
        payload = json.loads(bytes(self.serializer.serialize(event)))
        self.assertNotIn("attributes", payload)
        context.close()


class FactorySystemAttributesTest(unittest.TestCase):
    """The configured application/environment reach audiences through the
    public ABsmartly factories, including when both a custom provider and a
    custom publisher are supplied (the configured client must still be
    retained). Reference: JavaScript SDK PR #68.
    """

    deser = DefaultContextDataDeserializer()

    def build_sdk(self, custom_components):
        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.api_key = "gfsgsgsf"
        client_config.application = "website"
        client_config.environment = "production"
        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        client = ClientContextMock(client_config, http_client)

        config = ABsmartlyConfig()
        config.client = client
        if custom_components:
            # Both components supplied: __init__ must still keep the client.
            config.context_data_provider = \
                DefaultContextDataProvider(client)
            config.context_publisher = DefaultContextEventHandler(client)
        return ABsmartly(config)

    def full_on_environment_data(self):
        experiment = {
            "id": 1,
            "name": "exp_test_ab",
            "iteration": 1,
            "unitType": "session_id",
            "seedHi": 3603515,
            "seedLo": 233373850,
            "split": [0.5, 0.5],
            "trafficSeedHi": 449867249,
            "trafficSeedLo": 455443629,
            "trafficSplit": [0.0, 1.0],
            "fullOnVariant": 1,
            "applications": [{"name": "website"}],
            "variants": [
                {"name": "A", "config": None},
                {"name": "B", "config": None},
            ],
            "audienceStrict": True,
            "audience": json.dumps({
                "filter": [
                    {"eq": [{"var": "environment"}, {"value": "production"}]}
                ]
            }),
        }
        content = json.dumps({"experiments": [experiment]})
        return self.deser.deserialize(
            bytes(content, encoding="utf-8"), 0, len(content))

    def context_config(self):
        config = ContextConfig()
        config.units = {
            "session_id": "e791e240fcd3df7d238cfc285f475e8152fcc0ec"}
        return config

    def test_create_context_default_components_sees_names(self):
        for custom in (False, True):
            with self.subTest(custom_components=custom):
                sdk = self.build_sdk(custom)
                sdk.client._refresh_data = self.full_on_environment_data()
                context = sdk.create_context(self.context_config())
                context.wait_until_ready()
                self.assertEqual(1, context.get_treatment("exp_test_ab"))
                self.assertEqual(
                    {"application": "website", "environment": "production"},
                    context._build_audience_attributes())
                context.close()

    def test_create_context_with_sees_names(self):
        for custom in (False, True):
            with self.subTest(custom_components=custom):
                sdk = self.build_sdk(custom)
                context = sdk.create_context_with(
                    self.context_config(), self.full_on_environment_data())
                self.assertTrue(context.is_ready())
                self.assertEqual(1, context.get_treatment("exp_test_ab"))
                self.assertEqual(
                    {"application": "website", "environment": "production"},
                    context._build_audience_attributes())
                context.close()


if __name__ == "__main__":
    unittest.main()
