import time

from sdk.absmartly_config import ABSmartlyConfig

from sdk.context_config import ContextConfig

from sdk.absmarly import ABSmartly

from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig


def main():
    client_config = ClientConfig()
    client_config.endpoint = "https://sandbox.test.io/v1"
    client_config.api_key = "test"
    client_config.application = "www"
    client_config.environment = "prod"

    default_client_config = DefaultHTTPClientConfig()
    default_client = DefaultHTTPClient(default_client_config)
    sdk_config = ABSmartlyConfig()
    sdk_config.client = Client(client_config, default_client)
    sdk = ABSmartly(sdk_config)

    context_config = ContextConfig()
    context_config.publish_delay = 10
    context_config.refresh_interval = 5
    context_config.units = {"session_id": "bf06d8cb5d8137290c4abb64155584fbdb64d8",
                            "user_id": "12345"}
    ctx = sdk.create_context(context_config)
    print("context created")
    print("ready " + str(ctx.is_ready()))
    ctx.wait_until_ready()
    print("context ready " + str(ctx.is_ready()))
    treatment = ctx.get_treatment("exp_test_ab")
    print("ready " + str(ctx.is_ready()))
    print(treatment)
    print(ctx.exposures[0].name)
    print(ctx.get_data().experiments)

    properties = {"value": 125, "fee": 125}
    ctx.track("payment", properties)
    print("FINISH")
    print(ctx.is_closing())
    print(ctx.is_closed())
    print(client_config.executor)

    time.sleep(15)
    ctx.close()
    print(ctx.is_closing())
    print(ctx.is_closed())



if __name__ == '__main__':
    main()
