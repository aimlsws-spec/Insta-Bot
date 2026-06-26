"""
core/security.py
Password hashing, token generation, and the FastAPI auth dependency.

Import chain: core/security → models/user → database/mysql  (no circularity)
"""

import hashlib
import secrets
from typing import Optional

import bcrypt
from fastapi import HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _is_sha256(h: str) -> bool:
    return len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def verify_password(password: str, password_hash: str) -> bool:
    if _is_sha256(password_hash):
        return hashlib.sha256(password.encode()).hexdigest() == password_hash
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_token() -> str:
    return secrets.token_urlsafe(32)


_bearer = HTTPBearer(auto_error=False)


async def _token_from_header(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization.replace("Bearer ", "")
    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    token: Optional[str] = Depends(_token_from_header),
) -> str:
    from models.user import get_session

    auth_token = credentials.credentials if credentials else token
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authorization required")
    row = get_session(auth_token)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return row["user_id"]


async def get_current_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    token: Optional[str] = Depends(_token_from_header),
) -> str:
    auth_token = credentials.credentials if credentials else token
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authorization required")
    return auth_token
