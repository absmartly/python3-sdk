import threading


class ReadWriteLock:
    """Reentrant read/write lock with no thread-ownership requirement on reads.

    Many readers may hold the lock together and may be released in any order
    or from any thread. A writer is exclusive and reentrant; the writing
    thread may also take read locks, and a thread that is the only reader may
    upgrade to write.
    """

    def __init__(self):
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._reader_threads = {}
        self._writer = None
        self._write_depth = 0

    def acquire_read(self):
        me = threading.get_ident()
        with self._cond:
            if self._writer != me:
                while self._writer is not None:
                    self._cond.wait()
            self._readers += 1
            self._reader_threads[me] = self._reader_threads.get(me, 0) + 1

    def release_read(self):
        me = threading.get_ident()
        with self._cond:
            assert self._readers > 0
            self._readers -= 1
            if me in self._reader_threads:
                self._reader_threads[me] -= 1
                if self._reader_threads[me] <= 0:
                    del self._reader_threads[me]
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self):
        me = threading.get_ident()
        with self._cond:
            if self._writer == me:
                self._write_depth += 1
                return
            while self._writer is not None or \
                    self._readers != self._reader_threads.get(me, 0):
                self._cond.wait()
            self._writer = me
            self._write_depth = 1

    def release_write(self):
        with self._cond:
            if self._writer != threading.get_ident():
                raise RuntimeError("cannot release un-acquired lock")
            self._write_depth -= 1
            if self._write_depth == 0:
                self._writer = None
                self._cond.notify_all()
