import base64
import hashlib


def hash_unit(unit: str) -> str:
    dig = hashlib.md5(unit.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(dig).rstrip(b'=').decode('ascii')
