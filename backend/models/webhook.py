"""models/webhook.py — DB queries for processed_webhooks deduplication table."""

from database.mysql import get_db


def is_processed(event_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id FROM processed_webhooks WHERE id = ?", (event_id,)
        )
        return cursor.fetchone() is not None


def mark_processed(event_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT IGNORE INTO processed_webhooks (id) VALUES (?)", (event_id,)
        )
        conn.commit()
