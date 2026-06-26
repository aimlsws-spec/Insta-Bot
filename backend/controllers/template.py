"""controllers/template.py — Message template create / list."""

import json
import uuid
from datetime import datetime

from models import template as template_model


def create(user_id: str, name: str, content: str, type: str, quick_replies: list) -> dict:
    tid = str(uuid.uuid4())
    template_model.create(
        tid, user_id, name, content, type,
        json.dumps(quick_replies or []),
        datetime.now().isoformat(),
    )
    return {"template_id": tid}


def list_templates(user_id: str) -> dict:
    rows = template_model.get_all_by_user(user_id)
    return {
        "templates": [
            dict(row, quick_replies=json.loads(row["quick_replies"]) if row["quick_replies"] else [])
            for row in rows
        ]
    }
