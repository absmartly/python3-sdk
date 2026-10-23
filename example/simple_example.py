#!/usr/bin/env python3

from sdk import ABsmartly, ContextConfig


def main():
    # Create SDK with simple named parameters
    sdk = ABsmartly.create(
        endpoint="https://sandbox.absmartly.io/v1",
        api_key="YOUR-API-KEY",
        application="website",
        environment="development"
    )

    # Create a context
    context_config = ContextConfig()
    context_config.units = {
        "session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"
    }

    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()

    # Get treatment
    treatment = ctx.get_treatment("exp_test_experiment")
    print(f"Treatment: {treatment}")

    # Get variable with default
    button_color = ctx.get_variable_value("button.color", "blue")
    print(f"Button color: {button_color}")

    # Track a goal
    ctx.track("goal_clicked_button", {
        "button_color": button_color
    })

    # Close context
    ctx.close()
    print("Context closed successfully")


def example_with_custom_options():
    # Create SDK with custom timeout and retries
    sdk = ABsmartly.create(
        endpoint="https://sandbox.absmartly.io/v1",
        api_key="YOUR-API-KEY",
        application="website",
        environment="development",
        timeout=5,      # 5 seconds timeout
        retries=3       # 3 max retries
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
    # Uncomment to run
    # main()

    print("\nRunning example with custom options...")
    # Uncomment to run
    # example_with_custom_options()
