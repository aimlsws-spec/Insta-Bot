"""controllers/auth.py — Registration, login, and current-user lookup."""

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException

from models import user as user_model
from core.security import hash_password, verify_password, generate_token, _is_sha256

_SESSION_DAYS = 30


def _expires_at() -> str:
    return (datetime.now() + timedelta(days=_SESSION_DAYS)).isoformat()


def register(email: str, password: str, name: str) -> dict:
    if user_model.find_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = str(uuid.uuid4())
    token   = generate_token()
    now     = datetime.now().isoformat()
    user_model.create_user(user_id, email, hash_password(password), name, "free", now)
    user_model.create_session(token, user_id, now, _expires_at())
    return {"token": token, "user": {"id": user_id, "email": email, "name": name, "plan": "free"}}


def login(email: str, password: str) -> dict:
    user = user_model.get_full_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if _is_sha256(user["password_hash"]):
        user_model.update_password_hash(user["id"], hash_password(password))
    token = generate_token()
    now   = datetime.now().isoformat()
    user_model.create_session(token, user["id"], now, _expires_at())
    return {
        "token": token,
        "user": {
            "id":    user["id"],
            "email": user["email"],
            "name":  user["name"],
            "plan":  user["subscription_plan"],
        },
    }


def logout(token: str) -> dict:
    user_model.delete_session(token)
    return {"message": "Logged out"}


def get_me(user_id: str) -> dict:
    user = user_model.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id":         user["id"],
        "email":      user["email"],
        "name":       user["name"],
        "plan":       user["subscription_plan"],
        "created_at": user["created_at"],
    }
