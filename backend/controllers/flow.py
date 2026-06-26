"""controllers/flow.py — Bot flow create / list / delete with JSON serialisation."""

import json
import uuid
from datetime import datetime

from models import flow as flow_model


def create(
    user_id: str, name: str, triggers: list, steps: list,
    reply_type: str, conditions: list, enabled: bool,
) -> dict:
    flow_id = str(uuid.uuid4())
    flow_model.create(
        flow_id, user_id, name,
        json.dumps(triggers),
        json.dumps(steps),
        reply_type,
        json.dumps(conditions or []),
        1 if enabled else 0,
        json.dumps({"triggered": 0, "completed": 0}),
        datetime.now().isoformat(),
    )
    return {"flow_id": flow_id}


def list_flows(user_id: str) -> dict:
    rows = flow_model.get_all_by_user(user_id)
    return {
        "flows": [
            dict(
                row,
                triggers=json.loads(row["triggers"]),
                steps=json.loads(row["steps"]),
                conditions=json.loads(row["conditions"]) if row["conditions"] else [],
                stats=json.loads(row["stats"]) if row["stats"] else {"triggered": 0, "completed": 0},
            )
            for row in rows
        ]
    }


def delete(flow_id: str, user_id: str) -> dict:
    flow_model.delete(flow_id, user_id)
    return {"message": "Deleted"}
