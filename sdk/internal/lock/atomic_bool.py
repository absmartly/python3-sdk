import threading


class AtomicBool(object):
    def __init__(self):
        self._value = False
        self._lock = threading.Lock()

    @property
    def value(self):
        with self._lock:
            return self._value

    @value.setter
    def value(self, val: bool):
        with self._lock:
            self._value = val

    def get(self):
        with self._lock:
            return self._value

    def set(self, value: bool):
        with self._lock:
            self._value = value

    def compare_and_set(self, expected_value: bool, new_value: bool):
        with self._lock:
            result = expected_value == self._value
            if result:
                self._value = new_value
            return result
