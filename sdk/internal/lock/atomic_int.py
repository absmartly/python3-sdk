import threading


class AtomicInt(object):
    def __init__(self):
        self.value = 0
        self._lock = threading.Lock()

    def set(self, value: int):
        with self._lock:
            self.value = value

    def increment(self):
        with self._lock:
            self.value += 1

    def increment_and_get(self):
        with self._lock:
            self.value += 1
            return self.value

    def get(self):
        with self._lock:
            return self.value
