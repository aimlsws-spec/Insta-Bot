"""controllers/analytics.py — Analytics aggregation."""

from models import analytics as analytics_model


def get_analytics(user_id: str) -> dict:
    rows = [dict(row) for row in analytics_model.get_all_by_user(user_id)]
    return {
        "daily": {r["date"]: r for r in rows},
        "totals": {
            "messages_sent":     sum(r["messages_sent"]     for r in rows),
            "messages_received": sum(r["messages_received"] for r in rows),
            "comments_replied":  sum(r["comments_replied"]  for r in rows),
        },
    }
