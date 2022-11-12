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
    def compute_if_absent_rw(lock: ReadWriteLock,
                             mp: dict,
                             key: object, computer):
        try:
            lock.acquire_read()
            if key in mp:
                return mp[key]
        finally:
            lock.release_read()

        try:
            lock.acquire_write()
            if key in mp:
                return mp[key]

            new_value = computer(key)
            mp[key] = new_value
            return new_value
        finally:
            lock.release_write()

    @staticmethod
    def get_rw(lock: ReadWriteLock, mp: dict, key: object):
        try:
            lock.acquire_write()
            if key not in mp:
                return None
            else:
                return mp[key]
        finally:
            lock.release_write()

    @staticmethod
    def put_rw(lock: ReadWriteLock, mp: dict, key: object, value: object):
        try:
            lock.acquire_write()
            previous = None
            if key in mp:
                previous = mp[key]
            mp[key] = value
            return previous
        finally:
            lock.release_write()
