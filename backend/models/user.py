"""models/user.py — DB queries for users and sessions tables."""

from database.mysql import get_db


def find_by_email(email: str):
    with get_db() as conn:
        cursor = conn.execute("SELECT id FROM users WHERE email = ?", (email,))
        return cursor.fetchone()


def get_full_by_email(email: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, email, name, password_hash, subscription_plan FROM users WHERE email = ?",
            (email,),
        )
        return cursor.fetchone()


def get_by_id(user_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, email, name, subscription_plan, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        return cursor.fetchone()


def get_subscription_plan(user_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT subscription_plan FROM users WHERE id = ?", (user_id,)
        )
        return cursor.fetchone()


def create_user(
    user_id: str, email: str, password_hash: str, name: str, plan: str, created_at: str
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, name, subscription_plan, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email, password_hash, name, plan, created_at),
        )
        conn.commit()


def update_password_hash(user_id: str, password_hash: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()


def create_session(token: str, user_id: str, created_at: str, expires_at: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, created_at, expires_at),
        )
        conn.commit()


def get_session(token: str):
    from datetime import datetime
    now = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT user_id FROM sessions "
            "WHERE token = ? AND expires_at IS NOT NULL AND expires_at > ?",
            (token, now),
        )
        return cursor.fetchone()


def delete_session(token: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
