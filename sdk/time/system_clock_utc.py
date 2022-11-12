import time

from sdk.time.clock import Clock


class SystemClockUTC(Clock):
    def millis(self):
        return round(time.mktime(time.gmtime()) * 1000)
