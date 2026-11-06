# Changelog

## 0.3.0 (unreleased)

### BREAKING
- `ContextEventHandler` renamed to `ContextPublisher` (`context_event_handler` deprecated). The v0.2.4 import paths (`sdk.absmartly.ABSmartlyConfig`, `sdk.absmartly.DefaultContextEventHandler`, `ContextEventHandler` from `sdk.context_event_handler`, `sdk.absmartly_config` and `sdk.context`) still work and do not warn on import; `ContextEventHandler` stays a plain base class (a subclass without `publish` can still be instantiated) registered as a virtual `ContextPublisher`.
- `get_custom_field_type` renamed.
- `get_variable_keys()` returns `Dict[str, List[str]]`: for each variable key, the names of every experiment defining it, in experiment id order. This intentionally differs from v0.2.4 (one experiment name string per key) to match the JS SDK's `variableKeys()`.
- **BREAKING:** read methods now raise "ABSmartly Context is not yet ready" before the context is ready, and the closed error after close, instead of returning defaults. A context whose load failed is ready and returns control/default values.
- JSON expr `in` operator is haystack-first (CONTAINS semantics); `eq(null, null)` returns null.
- `set_unit` keeps numeric UIDs as numbers (hashed like the JS SDK, e.g. `125.75` hashes as `"126"`) and rejects values that are neither a string nor a number with "Unit '<type>' must be a string or a number.".
- `track` raises "Goal '<name>' properties must be of type object." when properties cannot be converted with `dict()`; any `Mapping` or list of pairs is still accepted, as in v0.2.4.

### Added
- `ContextError(RuntimeError)` / `ContextValueError(ValueError)`: lifecycle and unit errors keep their v0.2.4 messages (`'ABSmartly Context is closed'`, `'ABSmartly Context is closing'`, `'ABSmartly Context is not yet ready'`, `'Unit already set.'`, `'Unit UID must not be blank.'`) and expose the cross-SDK wording as `canonical_message`.
- `sdk.utils`: `hash_unit`, `utf8_bytes`, `base64_url_no_padding`, `is_object`, `is_numeric`, `is_promise`.
- Finalize aliases, `get_unit`, `get_units`, `get_attribute`, `get_attributes`, `ready_error`; `EventType` export.
- `custom_assignments` (deprecated alias for the `cassigmnents` typo).
- `Context.cassignments` kept as a deprecated property (with setter) proxying `Context.custom_assignments`.

### Fixed
- `DefaultVariableParser.parse` and `DefaultContextDataDeserializer.deserialize` return `None` on invalid input again, as in v0.2.4. Context logs an ERROR for an unparseable variant config, or one that is not a JSON object (no variables are indexed for it), and treats `None` context data as a failed load (or a failed refresh) instead of hanging.
- `DefaultHTTPClient` accepts v0.2.4-style configs without `retry_status_forcelist` / `retry_allowed_methods` and uses the v0.2.4 policy for them.
- `get_variable_value`/`peek_variable_value` with a key shared by several experiments follow the JS SDK: experiments are visited in id order, the value comes from the first one the unit is assigned to or overridden in, and each visited experiment is exposed.
- Audience regex matching no longer runs in a thread pool or caps pattern length (the timeout could not interrupt a match); invalid patterns still evaluate to `None`.
- `DefaultHTTPClient` keeps the v0.2.4 retry policy (GET/POST on 502/503, publish PUT not retried) with `raise_on_status=False`; the wider policy is opt-in via `DefaultHTTPClientConfig.retry_status_forcelist` / `retry_allowed_methods`.
- A cached assignment records the attribute sequence after an unchanged audience re-check, so it is not re-evaluated on every read.
- `refresh()` works before the context is ready and on a context whose first fetch failed, as in v0.2.4; a successful refresh clears the failed state so new exposures and queued goals are published (control exposures queued while failed are dropped). If the initial fetch completes after a pre-ready refresh, it does not replace the refreshed data or log `READY`.
- `close()` logs `EventType.CLOSE` again (as in v0.2.4), followed by the new `EventType.FINALIZE`.
- A failed final publish no longer restarts the refresh timer; the events stay queued so `close()` can be retried.
- The `ready`, `error`, `refresh` and `finalize` events are logged before the matching future settles, so callers woken by it already see the event.
- Custom field values parsed lazily; refresh timer race; daemon timer threads; owner-safe ReadWriteLock; `DefaultHTTPClient.post` uses POST.
