"""Authentication primitives: Argon2id password hashing, opaque session tokens."""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()  # defaults are Argon2id with OWASP-sane parameters


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def new_session_token() -> tuple[str, str]:
    """Return (plaintext_token, sha256_hex) — store only the hash, cookie carries plaintext."""
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    return token, digest


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
