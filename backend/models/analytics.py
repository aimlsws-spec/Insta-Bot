"""models/analytics.py — DB queries for analytics table."""

from database.mysql import get_db


def get_all_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM analytics WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchall()


def upsert_dm(user_id: str, date: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO analytics (user_id, date, messages_sent, messages_received)
               VALUES (?, ?, 1, 1)
               ON DUPLICATE KEY UPDATE
                   messages_sent     = messages_sent + 1,
                   messages_received = messages_received + 1""",
            (user_id, date),
        )
        conn.commit()


def upsert_comment(user_id: str, date: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO analytics (user_id, date, comments_replied)
               VALUES (?, ?, 1)
               ON DUPLICATE KEY UPDATE
                   comments_replied = comments_replied + 1""",
            (user_id, date),
        )
        conn.commit()
