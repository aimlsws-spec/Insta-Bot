"""controllers/conversation.py — Conversation listing."""

import json
from models import conversation as conv_model


def list_conversations(user_id: str) -> dict:
    rows = conv_model.get_all_by_user(user_id)
    return {
        "conversations": [
            dict(row, messages=json.loads(row["messages"])) for row in rows
        ]
    }
