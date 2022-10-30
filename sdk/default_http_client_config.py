class DefaultHTTPClientConfig:
    def __init__(self):
        self.connection_timeout = 3  # seconds
        self.connection_request_timeout = 1
        self.retry_interval = 0.3
        self.max_retries = 5
