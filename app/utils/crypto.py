import base64
import hashlib
import math
import secrets
import string
import uuid
import time
import urllib.parse

# Phase 2F — explicit alphabet and pool size constants
_PASSWORD_ALPHABET: str = string.ascii_letters + string.digits + "!@#$%^&*"
_PASSWORD_POOL_SIZE: int = 70  # len(_PASSWORD_ALPHABET)

def gen_uuid() -> str:
    return str(uuid.uuid4())

def gen_password(length: int = 16) -> str:
    return ''.join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))

def gen_password_entropy(length: int) -> float:
    """Return entropy in bits: length * log2(pool_size)."""
    return length * math.log2(_PASSWORD_POOL_SIZE)

# Phase 2H — local common-password detection (no network; top-100 list)
_COMMON_PASSWORDS: frozenset = frozenset({
    "password", "123456", "123456789", "12345678", "12345", "1234567",
    "password1", "password123", "qwerty", "qwerty123", "111111", "1234567890",
    "000000", "abc123", "iloveyou", "dragon", "master", "monkey", "letmein",
    "login", "admin", "welcome", "sunshine", "princess", "solo", "superman",
    "michael", "shadow", "654321", "121212", "football", "baseball", "soccer",
    "hockey", "charlie", "donald", "pussy", "jordan", "harley", "ranger",
    "trustno1", "hunter", "batman", "access", "mustang", "1q2w3e4r",
    "passw0rd", "qwertyuiop", "asdfghjkl", "zxcvbnm", "starwars",
    "hello", "hello123", "cheese", "buster", "jessica", "daniel",
    "thomas", "andrew", "george", "jordan", "jennifer", "joshua", "justin",
    "555555", "666666", "777777", "888888", "999999", "pass", "test",
    "guest", "user", "root", "toor", "changeme", "default", "pass123",
    "1111111", "11111111", "123123", "1234", "12341234", "abc",
    "password2", "p@ssword", "p@ssw0rd", "Pa$$word", "passw0rd1",
    "monkey1", "dragon1", "master1", "qwerty1", "sunshine1",
})


def check_password_strength(password: str) -> str:
    """Legacy API — returns label string. Preserved for backward compatibility."""
    score = 0
    if len(password) >= 8: score += 1
    if len(password) >= 12: score += 1
    if any(c.islower() for c in password) and any(c.isupper() for c in password): score += 1
    if any(c.isdigit() for c in password): score += 1
    if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password): score += 1

    if score >= 5: return "Very Strong 🔒"
    elif score == 4: return "Strong ✅"
    elif score == 3: return "Moderate ⚠️"
    return "Weak ❌"


def check_password_strength_detailed(password: str) -> dict:
    """
    Phase 2H: Full breakdown with per-criterion results and common-password flag.
    Returns:
        score        int  0-5
        label        str
        checks       dict of bool
        is_common    bool
    """
    c_len8      = len(password) >= 8
    c_len12     = len(password) >= 12
    c_mixed     = (any(c.islower() for c in password)
                   and any(c.isupper() for c in password))
    c_digit     = any(c.isdigit() for c in password)
    c_symbol    = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
    is_common   = password.lower() in _COMMON_PASSWORDS

    score = sum([c_len8, c_len12, c_mixed, c_digit, c_symbol])
    if is_common:
        score = min(score, 1)  # cap at Weak when common

    if score >= 5:   label = "Very Strong 🔒"
    elif score == 4: label = "Strong ✅"
    elif score == 3: label = "Moderate ⚠️"
    else:            label = "Weak ❌"

    return {
        "score":     score,
        "label":     label,
        "length":    len(password),
        "checks": {
            "length_8":    c_len8,
            "length_12":   c_len12,
            "mixed_case":  c_mixed,
            "has_digits":  c_digit,
            "has_symbols": c_symbol,
        },
        "is_common": is_common,
    }

def gen_hashes(text: str) -> tuple:
    b = text.encode('utf-8')
    return (
        hashlib.md5(b).hexdigest(),
        hashlib.sha256(b).hexdigest(),
        hashlib.sha512(b).hexdigest(),
        # SHA-3 family (FIPS 202)
        hashlib.sha3_224(b).hexdigest(),
        hashlib.sha3_256(b).hexdigest(),
        hashlib.sha3_384(b).hexdigest(),
        hashlib.sha3_512(b).hexdigest(),
        # BLAKE2 family
        hashlib.blake2b(b).hexdigest(),
        hashlib.blake2s(b).hexdigest(),
    )

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
