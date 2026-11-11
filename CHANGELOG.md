# Changelog

## 0.3.0 (unreleased)

### BREAKING
- `ContextEventHandler` renamed to `ContextPublisher` (`context_event_handler` deprecated). The v0.2.4 import paths (`sdk.absmartly.ABSmartlyConfig`, `sdk.absmartly.DefaultContextEventHandler`, `ContextEventHandler` from `sdk.context_event_handler`, `sdk.absmartly_config` and `sdk.context`) still work and do not warn on import; `ContextEventHandler` stays a plain base class (a subclass without `publish` can still be instantiated) registered as a virtual `ContextPublisher`.
- `get_custom_field_type` renamed.
- `get_variable_keys()` keeps the v0.2.4 shape (one experiment name string per key), but when several experiments define a key it now returns the lowest-id experiment instead of v0.2.4's last-in-payload one.
- `get_variable_value`/`peek_variable_value` with a key shared by several experiments now take the value from the lowest-id experiment the unit is assigned to or overridden in (visiting experiments in id order), instead of v0.2.4's last-in-payload experiment; each visited experiment is exposed.
- Audiences are re-evaluated after `set_attribute`: a unit whose attributes change can move in or out of an experiment's audience (so between assigned and the control/default value), which emits the extra exposure for the re-evaluated experiment. v0.2.4 evaluated the audience only once.
- **BREAKING:** read methods now raise "ABSmartly Context is not yet ready" before the context is ready, and the closed error after close, instead of returning defaults. A context whose load failed is ready and returns control/default values.
- JSON expr `in` operator is haystack-first (CONTAINS semantics); `eq(null, null)` returns null.
- `set_unit` keeps numeric UIDs as numbers (hashed like the JS SDK, e.g. `125.75` hashes as `"126"`) and rejects values that are neither a string nor a number with "Unit '<type>' must be a string or a number.".
- `track` raises "Goal '<name>' properties must be of type object." when properties cannot be converted with `dict()`; any `Mapping` or list of pairs is still accepted, as in v0.2.4.

### Changed
- Audiences and assignment-rule conditions are now always evaluated with `application` and `environment` set to the application and environment names configured in the SDK. They are layered under any user-set attributes (system values first, then your attributes overlay them), so a value you set with the same name — at any time, including after the context is created — always wins. Names that are not configured or empty are left out of the evaluation map. These system attributes are **not** published (the collector already attaches them to every event server-side) and `get_attributes()` does not return them. The SDK never adds `app_version` for audiences (an `app_version` you set yourself is still evaluated and published like any other attribute).

  **This changes assignment for running experiments.** A unit in an experiment with Audience enforced (`audienceStrict`) and an `environment` or `application` condition currently gets variant 0, even when it matches the condition and even when the experiment is full-on. After upgrading, a matching unit is randomised normally (or gets the full-on variant). Those experiments are broken today; this release fixes them, but their exposures will change.

### Added
- `Context.get_variable_keys_all()` returns every experiment defining each variable key, in experiment id order (matching the JS SDK's `variableKeys()`); `get_variable_keys()` keeps the v0.2.4 shape (one experiment name per key, the lowest id).
- `ContextError(RuntimeError)` / `ContextValueError(ValueError)`: lifecycle and unit errors keep their v0.2.4 messages (`'ABSmartly Context is closed'`, `'ABSmartly Context is closing'`, `'ABSmartly Context is not yet ready'`, `'Unit already set.'`, `'Unit UID must not be blank.'`) and expose the cross-SDK wording as `canonical_message`.
- `sdk.utils`: `hash_unit`, `utf8_bytes`, `base64_url_no_padding`, `is_object`, `is_numeric`, `is_promise`.
- Finalize aliases, `get_unit`, `get_units`, `get_attribute`, `get_attributes`, `ready_error`; `EventType` export.
- `custom_assignments` (deprecated alias for the `cassigmnents` typo).
- `Context.cassignments` kept as a deprecated property (with setter) proxying `Context.custom_assignments`.

### Fixed
- `DefaultVariableParser.parse` and `DefaultContextDataDeserializer.deserialize` return `None` on invalid input again, as in v0.2.4. Context logs an ERROR for an unparseable variant config, or one that is not a JSON object (no variables are indexed for it), and treats `None` context data as a failed load (or a failed refresh) instead of hanging.
- `DefaultHTTPClient` accepts v0.2.4-style configs without `retry_status_forcelist` / `retry_allowed_methods` and uses the v0.2.4 policy for them.
- Audience regex matching no longer runs in a thread pool or caps pattern length (the timeout could not interrupt a match); invalid patterns still evaluate to `None`.
- `DefaultHTTPClient` keeps the v0.2.4 retry policy (GET/POST on 502/503, publish PUT not retried) and its exhausted-retry behaviour (a `requests.exceptions.RetryError` once GET retries are exhausted); the wider policy is opt-in via `DefaultHTTPClientConfig.retry_status_forcelist` / `retry_allowed_methods`.
- A cached assignment records the attribute sequence after an unchanged audience re-check, so it is not re-evaluated on every read.
- `refresh()` works before the context is ready and on a context whose first fetch failed, as in v0.2.4; a successful refresh clears the failed state so new exposures and queued goals are published (control exposures queued while failed are dropped). If the initial fetch completes after a pre-ready refresh, it does not replace the refreshed data or log `READY`.
- The default publisher built by `ABsmartly` is a `DefaultContextEventHandler` again, so v0.2.4 `isinstance` checks against `DefaultContextEventHandler` and `ContextEventHandler` still hold.
- `close()` logs `EventType.CLOSE` again (as in v0.2.4), followed by the new `EventType.FINALIZE`.
- A failed final publish no longer restarts the refresh timer; the events stay queued so `close()` can be retried.
- The `ready`, `error`, `refresh` and `finalize` events are logged before the matching future settles, so callers woken by it already see the event.
- Custom field values parsed lazily; refresh timer race; daemon timer threads; owner-safe ReadWriteLock; `DefaultHTTPClient.post` uses POST.
