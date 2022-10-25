from sdk.time.clock import Clock


class FixedClock(Clock):
    def __init__(self, millis: int):
        self.millis = millis

    def millis(self):
        return self.millis