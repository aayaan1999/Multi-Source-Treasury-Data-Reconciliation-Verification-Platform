import base64
import hashlib
import hmac
import os
import time

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

_ITERATIONS = 200_000
_bearer = HTTPBearer(auto_error=False)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(_b64(digest), expected)
    except (ValueError, AttributeError):
        return False


# Verifying against this when the email is unknown keeps "no such user" and "wrong password" equally slow.
DUMMY_HASH = hash_password("not-a-real-password")


def create_token(user: dict) -> str:
    s = get_settings()
    now = int(time.time())
    claims = {
        "sub": str(user["user_id"]),
        "name": user["name"],
        "role": user["role"],
        "iat": now,
        "exp": now + s.jwt_expire_minutes * 60,
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Dependency for every protected route: returns the token's claims or raises 401."""
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        claims = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise unauthorized
    return {"user_id": int(claims["sub"]), "name": claims["name"], "role": claims["role"]}
