import threading


class AtomicBool(object):
    def __init__(self):
        self.value = False
        self._lock = threading.Lock()

    def set(self, value: bool):
        with self._lock:
            self.value = value

    def compare_and_set(self, expected_value: bool, new_value: bool):
        with self._lock:
            result = expected_value == self.value
            if result:
                self.value = new_value
            return result
