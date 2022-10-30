from sdk.time.clock import Clock


class FixedClock(Clock):
    def __init__(self, millis: int):
        self.value = millis

    def millis(self):
        return self.value
