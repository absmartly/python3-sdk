import time

from sdk.time.clock import Clock


class SystemClockUTC(Clock):
    def millis(self):
        return round(time.time() * 1000)
