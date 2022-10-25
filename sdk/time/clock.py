from abc import abstractmethod


class Clock:

    @abstractmethod
    def millis(self):
        raise NotImplementedError
