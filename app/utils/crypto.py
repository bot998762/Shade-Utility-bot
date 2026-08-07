import base64
import hashlib
import secrets
import string
import uuid
import time
import urllib.parse

def gen_uuid() -> str:
    return str(uuid.uuid4())

def gen_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def check_password_strength(password: str) -> str:
    score = 0
    if len(password) >= 8: score += 1
    if len(password) >= 12: score += 1
    if any(c.islower() for c in password) and any(c.isupper() for c in password): score += 1
    if any(c.isdigit() for c in password): score += 1
    if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password): score += 1
    
    if score >= 5: return "Very Strong 🔒"
    elif score >= 3: return "Moderate ⚠️"
    return "Weak ❌"

def gen_hashes(text: str) -> tuple:
    b = text.encode('utf-8')
    return hashlib.md5(b).hexdigest(), hashlib.sha256(b).hexdigest(), hashlib.sha512(b).hexdigest()

def b64_encode(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('utf-8')

def b64_decode(text: str) -> str:
    return base64.b64decode(text.encode('utf-8')).decode('utf-8')

def url_encode(text: str) -> str:
    return urllib.parse.quote(text)

def url_decode(text: str) -> str:
    return urllib.parse.unquote(text)

def current_time() -> int:
    return int(time.time())
