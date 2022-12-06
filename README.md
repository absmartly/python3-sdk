# A/B Smartly SDK

A/B Smartly - Python SDK

## Compatibility

The A/B Smartly Python SDK is compatible with Python 3.
It provides both a blocking and an asynchronous interfaces.


## Installation
pip install absmartly==0.1.2

### Python Modules
setuptools~=60.2.0  
requests~=2.28.1  
urllib3~=1.26.12  
jsons~=1.6.3

### Dependencies
sh ./run.sh

## Getting Started

Please follow the [installation](#installation) instructions before trying the following code:

#### Initialization
This example assumes an Api Key, an Application, and an Environment have been created in the A/B Smartly web console.
```python

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
    ctx = sdk.create_context(context_config)

   # ...
}
```

#### Creating a new Context synchronously
```python
# define a new context request
    context_config = ContextConfig()
    context_config.publish_delay = 10
    context_config.refresh_interval = 5
    context_config.units = {"session_id": "bf06d8cb5d8137290c4abb64155584fbdb64d8",
                            "user_id": "12345"}

    context_config = ContextConfig()
    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready()
```

#### Creating a new Context asynchronously
```python
# define a new context request
    context_config = ContextConfig()
    context_config.publish_delay = 10
    context_config.refresh_interval = 5
    context_config.units = {"session_id": "bf06d8cb5d8137290c4abb64155584fbdb64d8",
                            "user_id": "12345"}

    context_config = ContextConfig()
    ctx = sdk.create_context(context_config)
    ctx.wait_until_ready_async()
```

#### Setting extra units for a context
You can add additional units to a context by calling the `set_unit()` or the `set_units()` method.
This method may be used for example, when a user logs in to your application, and you want to use the new unit type to the context.
Please note that **you cannot override an already set unit type** as that would be a change of identity, and will throw an exception. In this case, you must create a new context instead.
The `SetUnit()` and `SetUnits()` methods can be called before the context is ready.

```python
context.set_unit("db_user_id", "1000013")

context.set_units({
		"db_user_id": "1000013"
})
```

#### Setting context attributes
The `set_attributes()` and `set_attributes()` methods can be called before the context is ready.
```python
context.set_attributes("user_agent", req.get_header("User-Agent"))

context.set_attributes({
        "customer_age": "new_customer"
})
```

#### Selecting a treatment
```python
res, _ = context.get_treatment("exp_test_experiment")
if res == 0:
        # user is in control group (variant 0)
else:
       # user is in treatment group
```

#### Tracking a goal achievement
Goals are created in the A/B Smartly web console.
```python
context.track("payment", {
        "item_count": 1,
        "total_amount": 1999.99
})
```

#### Publishing pending data
Sometimes it is necessary to ensure all events have been published to the A/B Smartly collector, before proceeding.
You can explicitly call the `publish()` or `publish_async()` methods.
```python
    context.publish()
```

#### Finalizing
The `close()` and `close_async()` methods will ensure all events have been published to the A/B Smartly collector, like `publish()`, and will also "seal" the context, throwing an error if any method that could generate an event is called.
```python
context.close()
```

#### Refreshing the context with fresh experiment data
For long-running contexts, the context is usually created once when the application is first started.
However, any experiments being tracked in your production code, but started after the context was created, will not be triggered.
To mitigate this, we can use the `set_refresh_interval()` method on the context config.

```python
    default_client_config = DefaultHTTPClientConfig()
    default_client_config.refresh_interval = 5
```

Alternatively, the `refresh()` method can be called manually.
The `refresh()` method pulls updated experiment data from the A/B Smartly collector and will trigger recently started experiments when `get_treatment()` is called again.
```python
context.refresh()
```

#### Using a custom Event Logger
The A/B Smartly SDK can be instantiated with an event logger used for all contexts.
In addition, an event logger can be specified when creating a particular context, in the `ContextConfig`.
```python
class EventType(Enum):
    ERROR = "error"
    READY = "ready"
    REFRESH = "refresh"
    PUBLISH = "publish"
    EXPOSURE = "exposure"
    GOAL = "goal"
    CLOSE = "close"


class ContextEventLogger:

    @abstractmethod
    def handle_event(self, event_type: EventType, data: object):
        raise NotImplementedError
```
The data parameter depends on the type of event.
Currently, the SDK logs the following events:

| event | when                                                       | data |
|:---: |------------------------------------------------------------|---|
| `Error` | `Context` receives an error                                | `Throwable` object |
| `Ready` | `Context` turns ready                                      | `ContextData` used to initialize the context |
| `Refresh` | `Context.refresh()` method succeeds                        | `ContextData` used to refresh the context |
| `Publish` | `Context.publish()` method succeeds                        | `PublishEvent` sent to the A/B Smartly event collector |
| `Exposure` | `Context.getTreatment()` method succeeds on first exposure | `Exposure` enqueued for publishing |
| `Goal` | `Context.track()` method succeeds                          | `GoalAchievement` enqueued for publishing |
| `Close` | `Context.close()` method succeeds the first time           | `null` |


#### Peek at treatment variants
Although generally not recommended, it is sometimes necessary to peek at a treatment or variable without triggering an exposure.
The A/B Smartly SDK provides a `peek_treament()` method for that.

```python
 res = context.peek_treamnet("exp_test_experiment")
if res == 0:
	# user is in control group (variant 0)
else:
	# user is in treatment group

```

##### Peeking at variables
```python
variable = context.peek_variable("my_variable")
```

#### Overriding treatment variants
During development, for example, it is useful to force a treatment for an experiment. This can be achieved with the `override()` and/or `overrides()` methods.
The `set_override()` and `set_overrides()` methods can be called before the context is ready.
```python
context.set_override("exp_test_experiment", 1) # force variant 1 of treatment
context.set_overrides({
	"exp_test_experiment": 1,
	"exp_another_experiment": 0
})
```

## About A/B Smartly
**A/B Smartly** is the leading provider of state-of-the-art, on-premises, full-stack experimentation platforms for engineering and product teams that want to confidently deploy features as fast as they can develop them.
A/B Smartly's real-time analytics helps engineering and product teams ensure that new features will improve the customer experience without breaking or degrading performance and/or business metrics.

### Have a look at our growing list of clients and SDKs:
- [Java SDK](https://www.github.com/absmartly/java-sdk)
- [JavaScript SDK](https://www.github.com/absmartly/javascript-sdk)
- [PHP SDK](https://www.github.com/absmartly/php-sdk)
- [Swift SDK](https://www.github.com/absmartly/swift-sdk)
- [Vue2 SDK](https://www.github.com/absmartly/vue2-sdk)
- [Go SDK](https://www.github.com/absmartly/go-sdk)
- [Ruby SDK](https://www.github.com/absmartly/ruby-sdk)