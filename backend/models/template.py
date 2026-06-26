"""models/template.py — DB queries for message_templates table."""

from database.mysql import get_db


def create(
    id: str, user_id: str, name: str, content: str,
    type: str, quick_replies: str, created_at: str,
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO message_templates "
            "(id, user_id, name, content, type, quick_replies, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, user_id, name, content, type, quick_replies, created_at),
        )
        conn.commit()


def get_all_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM message_templates WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchall()


def get_content(template_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT content FROM message_templates WHERE id = ?", (template_id,)
        )
        return cursor.fetchone()
