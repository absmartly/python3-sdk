from sdk.internal.lock.read_write_lock import ReadWriteLock


class Concurrency:

    @staticmethod
    def add_rw(lock: ReadWriteLock, lst: list, value: object):
        try:
            lock.acquire_write()
            lst.append(value)
        finally:
            lock.release_write()

    @staticmethod
    def compute_if_absent_rw(self, lock: ReadWriteLock, map: dict, key: object, computer):
        try:
            lock.acquire_read()
            value = map[key]
            if value is not None:
                return value
        finally:
            lock.release_read()

        try:
            lock.acquire_write()
            value = map[key]
            if value is not None:
                return value

            new_value = computer(key)
            map[key] = new_value
            return new_value
        finally:
            lock.release_write()
