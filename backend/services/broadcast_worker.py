"""
services/broadcast_worker.py
Asyncio background task that polls for scheduled broadcasts and sends them.

Lifecycle: started once at app startup via asyncio.create_task().
"""

import asyncio
from datetime import datetime

from models   import broadcast    as broadcast_model
from models   import conversation as conv_model
from models   import instagram    as ig_model
from services import instagram_api

_POLL_INTERVAL = 30  # seconds


async def _send_broadcast(broadcast: dict) -> None:
    bid     = broadcast["id"]
    user_id = broadcast["user_id"]
    content = broadcast["content"]

    accounts = ig_model.get_all_by_user(user_id)
    if not accounts:
        print(f"[broadcast] {bid} — no Instagram account for user {user_id}, marking failed")
        broadcast_model.mark_failed(bid)
        return

    token          = accounts[0]["access_token"]
    ig_account_id  = accounts[0]["instagram_id"]

    sender_ids = conv_model.get_real_sender_ids(user_id)
    if not sender_ids:
        print(f"[broadcast] {bid} — no subscribers for user {user_id}, marking sent(0)")
        broadcast_model.mark_sent(bid, 0)
        return

    sent = 0
    for sid in sender_ids:
        try:
            await instagram_api.send_message(token, ig_account_id, sid, content)
            sent += 1
        except Exception as e:
            print(f"[broadcast] {bid} — failed to send to {sid}: {e}")

    broadcast_model.mark_sent(bid, sent)
    print(f"[broadcast] {bid} — sent to {sent}/{len(sender_ids)} subscribers")


async def run_worker() -> None:
    print("[broadcast_worker] started — polling every 30s")
    while True:
        try:
            now     = datetime.now().isoformat()
            pending = broadcast_model.get_pending(now)
            if pending:
                print(f"[broadcast_worker] {len(pending)} pending broadcast(s)")
                for broadcast in pending:
                    await _send_broadcast(broadcast)
        except Exception as e:
            print(f"[broadcast_worker] poll error: {e}")
        await asyncio.sleep(_POLL_INTERVAL)
