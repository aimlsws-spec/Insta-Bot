"""controllers/broadcast.py — Broadcast create / list / delete."""

import json
import uuid
from datetime import datetime

from models import broadcast as broadcast_model


def create(
    user_id: str, name: str, content: str, target_tags: list, schedule_time,
) -> dict:
    bid = str(uuid.uuid4())
    broadcast_model.create(
        bid, user_id, name, content,
        json.dumps(target_tags or []),
        schedule_time,
        "draft",
        datetime.now().isoformat(),
    )
    return {"broadcast_id": bid}


def list_broadcasts(user_id: str) -> dict:
    rows = broadcast_model.get_all_by_user(user_id)
    return {
        "broadcasts": [
            dict(row, target_tags=json.loads(row["target_tags"]) if row["target_tags"] else [])
            for row in rows
        ]
    }


def delete(broadcast_id: str, user_id: str) -> dict:
    broadcast_model.delete(broadcast_id, user_id)
    return {"message": "Deleted"}
