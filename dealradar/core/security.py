import hashlib
import hmac
import os

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P)
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---- session tokens: "<user_id>.<expires>.<hmac>" ----
import base64
import time


def _sig(secret: str, payload: str) -> str:
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_token(secret: str, user_id: str, ttl_seconds: int, now: float | None = None) -> str:
    payload = f"{user_id}.{int((now if now is not None else time.time()) + ttl_seconds)}"
    return f"{payload}.{_sig(secret, payload)}"


def verify_token(secret: str, token: str, now: float | None = None) -> str | None:
    """Return the user id if the token is authentic and unexpired."""
    try:
        user_id, expires, sig = token.rsplit(".", 2)
        if not hmac.compare_digest(sig, _sig(secret, f"{user_id}.{expires}")):
            return None
        if int(expires) < (now if now is not None else time.time()):
            return None
    except ValueError:
        return None
    return user_id
