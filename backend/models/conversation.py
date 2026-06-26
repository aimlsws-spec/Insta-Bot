"""models/conversation.py — DB queries for conversations table."""

from database.mysql import get_db


def get_by_id(conv_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT messages FROM conversations WHERE id = ?", (conv_id,)
        )
        return cursor.fetchone()


def get_all_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchall()


def get_real_sender_ids(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT DISTINCT sender_id FROM conversations "
            "WHERE user_id = ? AND is_test = 0",
            (user_id,),
        )
        return [row["sender_id"] for row in cursor.fetchall()]


def create(
    id: str, user_id: str, instagram_account_id: str, sender_id: str,
    messages: str, last_activity: str, is_test: int = 0,
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO conversations "
            "(id, user_id, instagram_account_id, sender_id, messages, last_activity, is_test) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, user_id, instagram_account_id, sender_id, messages, last_activity, is_test),
        )
        conn.commit()


def update(conv_id: str, messages: str, last_activity: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE conversations SET messages = ?, last_activity = ? WHERE id = ?",
            (messages, last_activity, conv_id),
        )
        conn.commit()


def upsert_test(
    id: str, user_id: str, instagram_account_id: str, sender_id: str,
    messages: str, last_activity: str, is_test: int,
) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO conversations
                   (id, user_id, instagram_account_id, sender_id, messages, last_activity, is_test)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON DUPLICATE KEY UPDATE
                   messages      = VALUES(messages),
                   last_activity = VALUES(last_activity)""",
            (id, user_id, instagram_account_id, sender_id, messages, last_activity, is_test),
        )
        conn.commit()
