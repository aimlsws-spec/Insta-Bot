"""models/flow.py — DB queries for bot_flows table."""

from database.mysql import get_db


def create(
    id: str, user_id: str, name: str, triggers: str, steps: str,
    reply_type: str, conditions: str, enabled: int, stats: str, created_at: str,
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO bot_flows "
            "(id, user_id, name, triggers, steps, reply_type, conditions, enabled, stats, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, user_id, name, triggers, steps, reply_type, conditions, enabled, stats, created_at),
        )
        conn.commit()


def get_all_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM bot_flows WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchall()


def delete(flow_id: str, user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM bot_flows WHERE id = ? AND user_id = ?", (flow_id, user_id)
        )
        conn.commit()


def get_enabled_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM bot_flows WHERE user_id = ? AND enabled = 1", (user_id,)
        )
        return cursor.fetchall()
