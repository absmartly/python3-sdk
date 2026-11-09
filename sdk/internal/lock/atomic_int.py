import threading


class AtomicInt(object):
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    @property
    def value(self):
        with self._lock:
            return self._value

    @value.setter
    def value(self, value: int):
        with self._lock:
            self._value = value

    def set(self, value: int):
        with self._lock:
            self._value = value

    def increment(self):
        with self._lock:
            self._value += 1

    def increment_and_get(self):
        with self._lock:
            self._value += 1
            return self._value

    def get(self):
        with self._lock:
            return self._value
