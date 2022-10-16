
class DefaultHTTPClientConfig:
    def __init__(self):
        self.connection_timeout = 3000
        self.connection_request_timeout = 1000
        self.retry_interval = 0.3
        self.max_retries = 5
