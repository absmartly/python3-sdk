class DefaultHTTPClientConfig:
    def __init__(self):
        self.connection_timeout = 3  # seconds
        self.connection_request_timeout = 1
        self.retry_interval = 0.3
        self.max_retries = 5
        # v0.2.4 retry policy: only GET/POST are retried, and only on 502/503,
        # so the publish PUT is never re-sent. Widen these (e.g. to every 5xx
        # and PUT, as the JS SDK does) only if the collector deduplicates.
        self.retry_status_forcelist = (502, 503)
        self.retry_allowed_methods = frozenset(['GET', 'POST'])
