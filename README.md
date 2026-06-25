# ABsmartly Python SDK

A/B Smartly - Python SDK

## Compatibility

The ABsmartly Python SDK is compatible with Python 3.
It provides both a blocking and an asynchronous interface.

## Installation

Install the SDK using pip:

```bash
pip install absmartly
```

### Dependencies

```
setuptools~=60.2.0
requests~=2.28.1
urllib3~=1.26.12
jsons~=1.6.3
```

## Getting Started

Please follow the [installation](#installation) instructions before trying the following code.

### Initialization

This example assumes an API Key, an Application, and an Environment have been created in the ABsmartly web console.

#### Recommended: Named Parameters

```python
from absmartly import ABsmartly, ContextConfig

def main():
    sdk = ABsmartly.create(
        endpoint="https://your-company.absmartly.io/v1",
        api_key="YOUR-API-KEY",
        application="website",
        environment="production"
    )

    context_config = ContextConfig()
    context_config.units = {"session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"}
    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()
```

#### With Optional Parameters

```python
from absmartly import ABsmartly, ContextConfig

sdk = ABsmartly.create(
    endpoint="https://your-company.absmartly.io/v1",
    api_key="YOUR-API-KEY",
    application="website",
    environment="production",
    timeout=5,      # Connection timeout in seconds (default: 3)
    retries=3       # Max retries on failure (default: 5)
)
```

#### Alternative: Manual Configuration

For use cases where you need to manually configure all components:

```python
from absmartly import (
    ABsmartly,
    ABsmartlyConfig,
    Client,
    ClientConfig,
    ContextConfig,
    DefaultHTTPClient,
    DefaultHTTPClientConfig,
)

def main():
    client_config = ClientConfig()
    client_config.endpoint = "https://your-company.absmartly.io/v1"
    client_config.api_key = "YOUR-API-KEY"
    client_config.application = "website"
    client_config.environment = "production"

    default_client_config = DefaultHTTPClientConfig()
    default_client_config.max_retries = 5
    default_client_config.connection_timeout = 3
    default_client = DefaultHTTPClient(default_client_config)

    sdk_config = ABsmartlyConfig()
    sdk_config.client = Client(client_config, default_client)
    sdk = ABsmartly(sdk_config)

    context_config = ContextConfig()
    context_config.units = {"session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"}
    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()
```

**SDK Options**

| Config                 | Type                                          | Required? | Default     | Description                                                                                                                                                                   |
| :--------------------- | :-------------------------------------------- | :-------: | :---------: | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| endpoint               | `str`                                         |  &#9989;  | `None`      | The URL to your API endpoint. Most commonly `"https://your-company.absmartly.io/v1"`                                                                                         |
| api_key                | `str`                                         |  &#9989;  | `None`      | Your API key which can be found on the Web Console.                                                                                                                           |
| environment            | `str`                                         |  &#9989;  | `None`      | The environment of the platform where the SDK is installed. Environments are created on the Web Console and should match the available environments in your infrastructure.   |
| application            | `str`                                         |  &#9989;  | `None`      | The name of the application where the SDK is installed. Applications are created on the Web Console and should match the applications where your experiments will be running. |
| timeout                | `int`                                         | &#10060;  | `3`         | Connection timeout in seconds before the SDK will stop trying to connect.                                                                                                     |
| retries                | `int`                                         | &#10060;  | `5`         | The number of retries before the SDK stops trying to connect.                                                                                                                 |
| event_logger           | `ContextEventLogger`                          | &#10060;  | `None`      | A callback handler which runs after SDK events.                                                                                                                               |
| context_data_provider  | `ContextDataProvider`                         | &#10060;  | auto        | Custom provider for context data (advanced usage, manual configuration only)                                                                                                  |
| context_event_handler  | `ContextEventHandler`                         | &#10060;  | auto        | Custom handler for publishing events (advanced usage, manual configuration only)                                                                                              |

## Creating a New Context

### Synchronously

```python
context_config = ContextConfig()
context_config.units = {"session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"}
context_config.publish_delay = 10
context_config.refresh_interval = 5

ctx = sdk.create_context(context_config)
ctx.wait_until_ready()

if ctx:
    print("Context ready")
```

### Asynchronously

```python
context_config = ContextConfig()
context_config.units = {"session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"}
context_config.publish_delay = 10
context_config.refresh_interval = 5

ctx = sdk.create_context(context_config)
ctx.wait_until_ready_async()
```

### With Pre-fetched Data

When doing full-stack experimentation with ABsmartly, we recommend creating a context only once on the server-side.
Creating a context involves a round-trip to the ABsmartly event collector.
We can avoid repeating the round-trip on the client-side by reusing the server-side context data.

```python
context_config = ContextConfig()
context_config.units = {
    "session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8",
    "user_id": "12345"
}

ctx = sdk.create_context(context_config)
ctx.wait_until_ready()

context_data = ctx.get_data()

another_config = ContextConfig()
another_config.units = {"session_id": "another-user-session-id"}

another_ctx = sdk.create_context_with(another_config, context_data)
```

### Refreshing the Context with Fresh Experiment Data

For long-running contexts, the context is usually created once when the application is first started.
However, any experiments being tracked in your production code, but started after the context was created, will not be triggered.
To mitigate this, we can use the `refresh_interval` parameter on the context config.

```python
context_config = ContextConfig()
context_config.units = {"session_id": "5ebf06d8cb5d8137290c4abb64155584fbdb64d8"}
context_config.refresh_interval = 5  # Refresh every 5 seconds

ctx = sdk.create_context(context_config)
```

Alternatively, the `refresh()` method can be called manually.
The `refresh()` method pulls updated experiment data from the ABsmartly collector and will trigger recently started experiments when `get_treatment()` is called again.

```python
context.refresh()
```

### Setting Extra Units

You can add additional units to a context by calling the `set_unit()` or the `set_units()` method.
This method may be used for example, when a user logs in to your application, and you want to use the new unit type to the context.

Please note that **you cannot override an already set unit type** as that would be a change of identity, and will throw an exception. In this case, you must create a new context instead.

The `set_unit()` and `set_units()` methods can be called before the context is ready.

```python
context.set_unit("db_user_id", "1000013")

context.set_units({
    "db_user_id": "1000013"
})
```

## Basic Usage

### Selecting a Treatment

```python
treatment = context.get_treatment("exp_test_experiment")

if treatment == 0:
    # User is in control group (variant 0)
    pass
else:
    # User is in treatment group
    pass
```

### Treatment Variables

```python
button_color = context.get_variable_value("button.color", "red")
```

### Peek at Treatment Variants

Although generally not recommended, it is sometimes necessary to peek at a treatment or variable without triggering an exposure.
The ABsmartly SDK provides a `peek_treatment()` method for that.

```python
treatment = context.peek_treatment("exp_test_experiment")

if treatment == 0:
    # User is in control group (variant 0)
    pass
else:
    # User is in treatment group
    pass
```

#### Peeking at Variables

```python
variable = context.peek_variable_value("my_variable", None)
```

### Overriding Treatment Variants

During development, for example, it is useful to force a treatment for an experiment. This can be achieved with the `set_override()` and/or `set_overrides()` methods.

The `set_override()` and `set_overrides()` methods can be called before the context is ready.

```python
context.set_override("exp_test_experiment", 1)

context.set_overrides({
    "exp_test_experiment": 1,
    "exp_another_experiment": 0
})
```

## Advanced

### Context Attributes

Attributes are used to pass meta-data about the user and/or the request.
They can be used later in the Web Console to create segments or audiences.

The `set_attribute()` and `set_attributes()` methods can be called before the context is ready.

```python
context.set_attribute("user_agent", request.headers.get("User-Agent"))

context.set_attributes({
    "customer_age": "new_customer",
    "account_type": "premium"
})
```

### Custom Assignments

Sometimes it may be necessary to override the automatic selection of a variant. For example, if you wish to have your variant chosen based on data from an API call. This can be accomplished using the `set_custom_assignment()` method.

```python
context.set_custom_assignment("exp_test_not_eligible", 3)
```

If you are running multiple experiments and need to choose different custom assignments for each one, you can do so using the `set_custom_assignments()` method.

```python
context.set_custom_assignments({
    "exp_test_experiment": 1,
    "exp_another_experiment": 2
})
```

### Tracking Goals

Goals are created in the ABsmartly web console.

```python
context.track("payment", {
    "item_count": 1,
    "total_amount": 1999.99
})
```

### Publishing Pending Data

Sometimes it is necessary to ensure all events have been published to the ABsmartly collector, before proceeding.
You can explicitly call the `publish()` or `publish_async()` methods.

```python
context.publish()

context.publish_async()
```

### Finalizing

The `close()` and `close_async()` methods will ensure all events have been published to the ABsmartly collector, like `publish()`, and will also "seal" the context, throwing an error if any method that could generate an event is called.

```python
context.close()

context.close_async()
```

### Custom Event Logger

The ABsmartly SDK can be instantiated with an event logger used for all contexts.
In addition, an event logger can be specified when creating a particular context, in the `ContextConfig`.

```python
from absmartly import ABsmartly, ContextEventLogger, EventType


class CustomEventLogger(ContextEventLogger):
    def handle_event(self, event_type: EventType, data):
        if event_type == EventType.ERROR:
            print(f"Error: {data}")
        elif event_type == EventType.READY:
            print("Context is ready")
        elif event_type == EventType.EXPOSURE:
            print(f"Exposed to experiment: {data.name}")
        elif event_type == EventType.GOAL:
            print(f"Goal tracked: {data.name}")
        elif event_type == EventType.REFRESH:
            print("Context refreshed")
        elif event_type == EventType.PUBLISH:
            print("Events published")
        elif event_type == EventType.CLOSE:
            print("Context closed")


sdk = ABsmartly.create(
    endpoint="https://your-company.absmartly.io/v1",
    api_key="YOUR-API-KEY",
    application="website",
    environment="production",
    event_logger=CustomEventLogger()
)

# Or with advanced configuration
sdk_config.context_event_logger = CustomEventLogger()
```

The data parameter depends on the type of event.

**Event Types**

| Event      | When                                                       | Data                                        |
| :--------- | :--------------------------------------------------------- | :------------------------------------------ |
| `Error`    | `Context` receives an error                                | Exception object                            |
| `Ready`    | `Context` turns ready                                      | `ContextData` used to initialize            |
| `Refresh`  | `Context.refresh()` method succeeds                        | `ContextData` used to refresh               |
| `Publish`  | `Context.publish()` method succeeds                        | `PublishEvent` sent to collector            |
| `Exposure` | `Context.get_treatment()` method succeeds on first exposure| `Exposure` enqueued for publishing          |
| `Goal`     | `Context.track()` method succeeds                          | `GoalAchievement` enqueued for publishing   |
| `Close`    | `Context.close()` method succeeds the first time           | `None`                                      |
| `Finalize` | `Context.close()` method succeeds                          | `None`                                      |

## Platform-Specific Examples

### Using with Flask

```python
from flask import Flask, session, render_template
from absmartly import ABsmartly, ContextConfig

app = Flask(__name__)

sdk = ABsmartly.create(
    endpoint="https://your-company.absmartly.io/v1",
    api_key="YOUR-API-KEY",
    application="website",
    environment="production"
)

@app.route('/')
def index():
    context_config = ContextConfig()
    context_config.units = {
        "session_id": session.get('session_id'),
        "user_id": session.get('user_id')
    }

    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()

    treatment = ctx.get_treatment("exp_test_experiment")

    if treatment == 0:
        return render_template('control.html')
    else:
        return render_template('treatment.html')
```

### Using with Django

```python
# settings.py
from absmartly import ABsmartly

ABSMARTLY_SDK = ABsmartly.create(
    endpoint="https://your-company.absmartly.io/v1",
    api_key="YOUR-API-KEY",
    application="website",
    environment="production"
)

# views.py
from django.conf import settings
from django.shortcuts import render
from absmartly import ContextConfig

def my_view(request):
    context_config = ContextConfig()
    context_config.units = {
        "session_id": request.session.session_key,
    }

    ctx = settings.ABSMARTLY_SDK.create_context(context_config)
    ctx.wait_until_ready()

    treatment = ctx.get_treatment("exp_test_experiment")

    context = {'treatment': treatment}
    return render(request, 'template.html', context)
```

### Using with FastAPI

```python
from fastapi import FastAPI, Request
from absmartly import ABsmartly, ContextConfig
import uuid

app = FastAPI()

sdk = ABsmartly.create(
    endpoint="https://your-company.absmartly.io/v1",
    api_key="YOUR-API-KEY",
    application="website",
    environment="production"
)

@app.get("/")
async def root(request: Request):
    context_config = ContextConfig()
    context_config.units = {
        "session_id": str(uuid.uuid4()),
    }

    ctx = sdk.create_context(context_config)
    await ctx.wait_until_ready_async()

    treatment = ctx.get_treatment("exp_test_experiment")

    return {"treatment": treatment}
```

## About A/B Smartly

**A/B Smartly** is the leading provider of state-of-the-art, on-premises, full-stack experimentation platforms for engineering and product teams that want to confidently deploy features as fast as they can develop them.
A/B Smartly's real-time analytics helps engineering and product teams ensure that new features will improve the customer experience without breaking or degrading performance and/or business metrics.

### Have a look at our growing list of clients and SDKs:
- [JavaScript SDK](https://www.github.com/absmartly/javascript-sdk)
- [Java SDK](https://www.github.com/absmartly/java-sdk)
- [PHP SDK](https://www.github.com/absmartly/php-sdk)
- [Swift SDK](https://www.github.com/absmartly/swift-sdk)
- [Vue2 SDK](https://www.github.com/absmartly/vue2-sdk)
- [Vue3 SDK](https://www.github.com/absmartly/vue3-sdk)
- [React SDK](https://www.github.com/absmartly/react-sdk)
- [Python3 SDK](https://www.github.com/absmartly/python3-sdk) (this package)
- [Go SDK](https://www.github.com/absmartly/go-sdk)
- [Ruby SDK](https://www.github.com/absmartly/ruby-sdk)
- [.NET SDK](https://www.github.com/absmartly/dotnet-sdk)
- [Dart SDK](https://www.github.com/absmartly/dart-sdk)
- [Flutter SDK](https://www.github.com/absmartly/flutter-sdk)
