# Changelog

## 0.3.0 (unreleased)

### BREAKING
- `ContextEventHandler` renamed to `ContextPublisher` (`context_event_handler` deprecated).
- `get_custom_field_type` renamed; `get_variable_keys` returns a list of experiment names; standardized error messages.
- **BREAKING:** read methods now raise "ABsmartly Context is not yet ready." before the context is ready, and a finalized error after finalize, instead of returning defaults. A context whose load failed is ready and returns control/default values.
- JSON expr `in` operator is haystack-first (CONTAINS semantics); `eq(null, null)` returns null.

### Added
- Finalize aliases, `get_unit`, `get_units`, `get_attribute`, `get_attributes`, `ready_error`; `EventType` export.
- `custom_assignments` (deprecated alias for the `cassigmnents` typo).

### Fixed
- Custom field values parsed lazily; refresh timer race; daemon timer threads; owner-safe ReadWriteLock; `DefaultHTTPClient.post` uses POST.
