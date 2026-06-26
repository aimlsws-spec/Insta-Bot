"""models/broadcast.py — DB queries for broadcasts table."""

from database.mysql import get_db


def create(
    id: str, user_id: str, name: str, content: str,
    target_tags: str, schedule_time, status: str, created_at: str,
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO broadcasts "
            "(id, user_id, name, content, target_tags, schedule_time, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, user_id, name, content, target_tags, schedule_time, status, created_at),
        )
        conn.commit()


def get_all_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM broadcasts WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchall()


def delete(broadcast_id: str, user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM broadcasts WHERE id = ? AND user_id = ?",
            (broadcast_id, user_id),
        )
        conn.commit()


def get_pending(now: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM broadcasts WHERE status = 'scheduled' AND schedule_time <= ?",
            (now,),
        )
        return cursor.fetchall()


def mark_sent(broadcast_id: str, sent_count: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE broadcasts SET status = 'sent', sent_count = ? WHERE id = ?",
            (sent_count, broadcast_id),
        )
        conn.commit()


def mark_failed(broadcast_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE broadcasts SET status = 'failed' WHERE id = ?",
            (broadcast_id,),
        )
        conn.commit()
