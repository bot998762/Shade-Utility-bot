import base64
import hashlib
import secrets
import string
import uuid
import time

def gen_uuid() -> str:
    return str(uuid.uuid4())

def gen_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def gen_hashes(text: str) -> tuple:
    b = text.encode('utf-8')
    return hashlib.md5(b).hexdigest(), hashlib.sha256(b).hexdigest()

def b64_encode(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('utf-8')

def b64_decode(text: str) -> str:
    return base64.b64decode(text.encode('utf-8')).decode('utf-8')

def current_time() -> int:
    return int(time.time())
