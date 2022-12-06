import threading


class ReadWriteLock:

    def __init__(self):
        self.w_lock = threading.RLock()
        self.num_r_lock = threading.RLock()
        self.num_r = 0

    def acquire_read(self):
        self.num_r_lock.acquire()
        self.num_r += 1
        if self.num_r == 1:
            self.w_lock.acquire()
        self.num_r_lock.release()

    def release_read(self):
        assert self.num_r > 0
        self.num_r_lock.acquire()
        self.num_r -= 1
        if self.num_r == 0:
            self.w_lock.release()
        self.num_r_lock.release()

    def acquire_write(self):
        self.w_lock.acquire()

    def release_write(self):
        self.w_lock.release()
