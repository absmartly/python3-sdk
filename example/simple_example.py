#!/usr/bin/env python3

from sdk import ABsmartly, ContextConfig


def main():
    sdk = ABsmartly.create(
        endpoint="https://sandbox.absmartly.io/v1",
        api_key="YOUR-API-KEY",
        application="website",
        environment="development"
    )

    context_config = ContextConfig()
    context_config.units = {
        "session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"
    }

    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()

    treatment = ctx.get_treatment("exp_test_experiment")
    print(f"Treatment: {treatment}")

    button_color = ctx.get_variable_value("button.color", "blue")
    print(f"Button color: {button_color}")

    ctx.track("goal_clicked_button", {
        "button_color": button_color
    })

    ctx.close()
    print("Context closed successfully")


def example_with_custom_options():
    sdk = ABsmartly.create(
        endpoint="https://sandbox.absmartly.io/v1",
        api_key="YOUR-API-KEY",
        application="website",
        environment="development",
        timeout=5,
        retries=3
    )

    context_config = ContextConfig()
    context_config.units = {"session_id": "test-session-123"}

    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()

    treatment = ctx.get_treatment("exp_test_experiment")
    print(f"Treatment with custom config: {treatment}")

    ctx.close()


if __name__ == "__main__":
    print("Running simple example...")
    # main()

    print("\nRunning example with custom options...")
    # example_with_custom_options()
