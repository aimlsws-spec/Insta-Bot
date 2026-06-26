"""
controllers/webhook.py
All webhook dispatch, DM/comment processing, reply matching, and test helpers.
"""

import json
import re
from datetime import datetime
from typing import List, Optional

from models   import instagram   as ig_model
from models   import conversation as conv_model
from models   import analytics    as analytics_model
from models   import flow         as flow_model
from models   import template     as template_model
from models   import webhook      as webhook_model
from services import instagram_api
from core.config import WEBHOOK_TEST_ID_MAP


# ─────────────────────────────────────────────────────────────────────────────
# Test / dev ID resolution
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_recipient_id(incoming_id: str) -> str:
    """Translate a webhook recipient ID to the real instagram_id stored in the DB.

    Meta's "Send Test" button uses dummy IDs (e.g. 23245) that don't match any
    row in instagram_accounts.  Add WEBHOOK_TEST_ID_MAP=23245:17841433733094314
    to .env to redirect test IDs to your real account without touching this code.

    Returns the original ID unchanged when no mapping is configured (production).
    """
    return WEBHOOK_TEST_ID_MAP.get(incoming_id, incoming_id)


# ─────────────────────────────────────────────────────────────────────────────
# Flow matching helpers  (single source of truth — used by all processors)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_keywords(triggers_json: str) -> list[str]:
    """
    Parse the stored triggers JSON and flatten comma-separated values.

    The UI lets users type "hello, hi, hey" in one field, which arrives as
    ["hello, hi, hey"].  This splits each item by commas so keyword matching
    works on individual tokens regardless of how they were entered.

    ["hello", "hi,hey", " price "] → ["hello", "hi", "hey", "price"]
    """
    keywords: list[str] = []
    for item in json.loads(triggers_json):
        for kw in item.split(","):
            kw = kw.strip().lower()
            if kw:
                keywords.append(kw)
    return keywords


def _keyword_matches(text_lower: str, keywords: list[str]) -> Optional[str]:
    """Return the first keyword that appears as a whole word in text, or None."""
    for kw in keywords:
        pattern = r'(?:\b|^){}(?:\b|$)'.format(re.escape(kw))
        if re.search(pattern, text_lower):
            return kw
    return None


def _get_message_content(row: dict) -> Optional[str]:
    """Return the first message or template step content from a flow row."""
    for step in json.loads(row["steps"]):
        if step.get("type") == "message":
            return step.get("content") or None
        if step.get("type") == "template":
            res = template_model.get_content(step.get("template_id"))
            if res:
                return res["content"]
    return None


def _get_dm_step_content(row: dict) -> Optional[str]:
    """Return the explicit DM step content from a flow row, or None if absent."""
    for step in json.loads(row["steps"]):
        if step.get("type") == "dm":
            return step.get("content") or None
    return None


def _find_matching_flow(
    text: str,
    user_id: str,
    channel: str,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    Scan enabled flows and return (matched_row, default_row).

    matched_row  — first flow whose keywords match `text`, filtered by channel
    default_row  — the "Default Reply" flow (captured before channel filter so
                   it works as a universal fallback for any channel)

    channel must be one of: "dm", "comment"
    """
    text_lower = text.lower().strip()
    rows       = flow_model.get_enabled_by_user(user_id)

    print(f"[flow] scanning {len(rows)} enabled flow(s): user={user_id} "
          f"channel={channel!r} text={text!r}")

    if not rows:
        print(f"[flow] WARNING: no enabled flows for user_id={user_id}")
        return None, None

    default_row: Optional[dict] = None

    for row in rows:
        flow_name_norm = row["name"].lower().strip()

        # Capture Default Reply BEFORE the channel filter so it is always
        # available as a fallback regardless of the flow's reply_type setting.
        if flow_name_norm == "default reply":
            default_row = row
            print(f"[flow] default reply captured: {repr(_get_message_content(row))}")
            continue

        # Skip flows whose reply_type doesn't serve this channel.
        if row["reply_type"] not in (channel, "both"):
            print(f"[flow] skip '{row['name']}' "
                  f"(reply_type={row['reply_type']!r} ≠ channel={channel!r})")
            continue

        keywords   = _parse_keywords(row["triggers"])
        matched_kw = _keyword_matches(text_lower, keywords)
        if matched_kw:
            print(f"[flow] TRIGGER MATCHED: flow='{row['name']}' "
                  f"keyword={matched_kw!r} message={text!r}")
            return row, default_row

        print(f"[flow] no match in '{row['name']}' "
              f"keywords={keywords} message={text!r}")

    return None, default_row


# ─────────────────────────────────────────────────────────────────────────────
# Core reply engine
# ─────────────────────────────────────────────────────────────────────────────

def generate_reply(
    message: str,
    user_id: str,
    conversation_history: Optional[List[dict]] = None,
    message_type: str = "dm",
) -> Optional[str]:
    matched_row, default_row = _find_matching_flow(message, user_id, message_type)

    if matched_row:
        content = _get_message_content(matched_row)
        if not content:
            print(f"[flow] WARNING: flow '{matched_row['name']}' matched "
                  f"but reply content is empty — check flow setup")
        return content

    if default_row:
        content = _get_message_content(default_row)
        print(f"[flow] no keyword match — using default reply: {repr(content)}")
        return content

    print(f"[flow] no match and no default reply — "
          f"bot stays silent for {repr(message)}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DM processing
# ─────────────────────────────────────────────────────────────────────────────

async def process_dm(sender_id: str, recipient_id: str, user_message: str,
                     entry_id: str = "") -> None:
    print(f"[dm] process_dm: sender={sender_id} recipient={recipient_id} "
          f"entry_id={entry_id} message={repr(user_message)}")

    # ── Resolve test IDs before any DB lookup ────────────────────────────────
    # _resolve_recipient_id maps dummy Meta test IDs to real DB IDs via .env.
    # In production the map is empty and IDs pass through unchanged.
    resolved_recipient = _resolve_recipient_id(recipient_id)
    resolved_entry     = _resolve_recipient_id(entry_id) if entry_id else entry_id
    if resolved_recipient != recipient_id:
        print(f"[dm] test ID mapped: recipient {recipient_id!r} → {resolved_recipient!r}")
    if resolved_entry != entry_id:
        print(f"[dm] test ID mapped: entry_id  {entry_id!r} → {resolved_entry!r}")

    # ── DB lookup: try resolved recipient first, then resolved entry_id ──────
    acc = ig_model.get_by_instagram_id(resolved_recipient)

    # Fallback: Facebook App webhooks send recipient.id = Page ID, not Instagram ID.
    # entry.id is always the subscribed account's Instagram Business Account ID.
    if not acc and resolved_entry and resolved_entry != resolved_recipient:
        print(f"[dm] {resolved_recipient!r} not in DB, retrying with entry_id={resolved_entry!r}")
        acc = ig_model.get_by_instagram_id(resolved_entry)

    # ── Graceful failure: acknowledge webhook (200) but log clearly ──────────
    # Returning here (not raising) lets the route handler respond 200 OK so
    # Meta does not keep retrying this delivery.
    if not acc:
        hint = (
            f"\n  hint: add WEBHOOK_TEST_ID_MAP={recipient_id}:YOUR_REAL_ID to .env"
            if not WEBHOOK_TEST_ID_MAP else ""
        )
        print(
            f"[dm] ACCOUNT NOT FOUND — webhook acknowledged to prevent Meta retry\n"
            f"  recipient_id received : {recipient_id!r}\n"
            f"  recipient_id resolved : {resolved_recipient!r}\n"
            f"  entry_id     received : {entry_id!r}\n"
            f"  entry_id     resolved : {resolved_entry!r}\n"
            f"  action: connect the Instagram account in the dashboard"
            + hint
        )
        return

    ig_account_id = acc["instagram_id"]
    username      = acc.get("username", "unknown")
    print(f"[dm] account resolved: @{username} (ig_id={ig_account_id})")

    # Skip webhook echoes — Instagram fires an echo when the bot itself sends a DM
    if sender_id == ig_account_id:
        print(f"[dm] skipping self-echo from bot account @{username}")
        return

    user_id, acc_id, token = acc["user_id"], acc["id"], acc["access_token"]
    conv_id  = f"{acc_id}_{sender_id}"
    row      = conv_model.get_by_id(conv_id)
    messages = json.loads(row["messages"]) if row else []

    bot_reply = generate_reply(user_message, user_id, messages, "dm")

    messages.append({"role": "user", "text": user_message, "ts": datetime.now().isoformat()})
    if bot_reply:
        messages.append({"role": "bot", "text": bot_reply, "ts": datetime.now().isoformat()})

    now = datetime.now().isoformat()
    if row:
        conv_model.update(conv_id, json.dumps(messages), now)
    else:
        conv_model.create(conv_id, user_id, acc_id, sender_id, json.dumps(messages), now)

    analytics_model.upsert_dm(user_id, datetime.now().date().isoformat())

    if bot_reply:
        print(f"[dm] sending reply to sender={sender_id} via @{username}: {repr(bot_reply)}")
        await instagram_api.send_message(token, ig_account_id, sender_id, bot_reply)
    else:
        print(f"[dm] no reply generated for message={repr(user_message)} — bot stays silent")


# ─────────────────────────────────────────────────────────────────────────────
# Comment processing
# ─────────────────────────────────────────────────────────────────────────────

async def process_comment(
    sender_id: str, comment_id: str, media_id: str, user_message: str,
    recipient_instagram_id: Optional[str] = None,
) -> None:
    print(f"[comment] process_comment: sender={sender_id} comment_id={comment_id} "
          f"media={media_id} message={repr(user_message)}")

    if not recipient_instagram_id:
        print("[comment] ERROR: called without recipient_instagram_id — skipped")
        return

    # Resolve test IDs before DB lookup (same mapping used by process_dm).
    resolved_ig_id = _resolve_recipient_id(recipient_instagram_id)
    if resolved_ig_id != recipient_instagram_id:
        print(f"[comment] test ID mapped: {recipient_instagram_id!r} → {resolved_ig_id!r}")

    acc = ig_model.get_by_instagram_id(resolved_ig_id)
    if not acc:
        print(
            f"[comment] ACCOUNT NOT FOUND — webhook acknowledged to prevent Meta retry\n"
            f"  instagram_id received : {recipient_instagram_id!r}\n"
            f"  instagram_id resolved : {resolved_ig_id!r}\n"
            f"  action: connect the Instagram account in the dashboard"
        )
        return

    user_id       = acc["user_id"]
    token         = acc["access_token"]
    ig_account_id = acc["instagram_id"]
    username      = acc.get("username", "unknown")
    print(f"[comment] account resolved: @{username} (ig_id={ig_account_id})")

    matched_row, default_row = _find_matching_flow(user_message, user_id, "comment")
    effective_row = matched_row or default_row

    if not effective_row:
        print(f"[comment] no matching flow — bot stays silent for {repr(user_message)}")
        return

    analytics_model.upsert_comment(user_id, datetime.now().date().isoformat())

    reply_type    = effective_row["reply_type"]
    comment_reply = _get_message_content(effective_row)

    # For "both" flows: use explicit dm step if present, otherwise reuse the
    # message content so the commenter always receives a DM follow-up.
    dm_reply: Optional[str] = None
    if reply_type == "both":
        dm_reply = _get_dm_step_content(effective_row) or comment_reply

    # ── Send comment reply ────────────────────────────────────────────────────
    if reply_type in ("comment", "both") and comment_reply:
        print(f"[comment] replying to comment {comment_id}: {repr(comment_reply)}")
        await instagram_api.send_comment_reply(token, comment_id, comment_reply)

    # ── Send DM follow-up (both only) ─────────────────────────────────────────
    if reply_type == "both" and dm_reply:
        if sender_id != ig_account_id:
            print(f"[comment] DM follow-up to commenter {sender_id}: {repr(dm_reply)}")
            await instagram_api.send_message(token, ig_account_id, sender_id, dm_reply)
        else:
            print("[comment] skipping DM follow-up — sender is the account owner")


# ─────────────────────────────────────────────────────────────────────────────
# Webhook event dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _extract_event_id(data: dict) -> Optional[str]:
    """Return a message-unique ID for deduplication, or None to skip dedup.

    Never use entry.id as fallback — it is the account ID and is identical
    across every webhook from that account, which would cause every DM after
    the first to be silently dropped as a duplicate.
    """
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            val = change.get("value", {})
            # val.get("id") = comment/post ID — unique per change event, safe to use
            mid = val.get("message", {}).get("mid") or val.get("id")
            if mid:
                return mid
        for msg in entry.get("messaging", []):
            mid = msg.get("message", {}).get("mid")
            if mid:
                return mid
    # No unique ID found — skip dedup rather than risk blocking real messages
    return None


async def handle_webhook(data: dict) -> dict:
    if "entry" not in data:
        return {"status": "ok"}

    event_id = _extract_event_id(data)
    if event_id:
        if webhook_model.is_processed(event_id):
            print(f"[webhook] duplicate event ignored: event_id={event_id}")
            return {"status": "duplicate_ignored"}
        webhook_model.mark_processed(event_id)
        print(f"[webhook] processing event_id={event_id}")
    else:
        print(f"[webhook] no unique event_id found — processing without dedup")

    for entry in data["entry"]:
        entry_id = str(entry.get("id", ""))

        if "changes" in entry:
            for change in entry["changes"]:
                field_name = change.get("field")
                print(f"[webhook] change field='{field_name}' entry_id={entry_id}")

                if field_name == "messages":
                    val          = change.get("value", {})
                    sender_id    = val.get("sender",    {}).get("id")
                    recipient_id = val.get("recipient", {}).get("id")
                    user_msg     = val.get("message",   {}).get("text")
                    print(f"[webhook] DM via changes: sender={sender_id} recipient={recipient_id} msg={repr(user_msg)}")
                    if sender_id and recipient_id and user_msg:
                        await process_dm(sender_id, recipient_id, user_msg, entry_id=entry_id)
                    else:
                        print(f"[webhook] WARNING: incomplete DM data — "
                              f"sender={sender_id} recipient={recipient_id} msg={repr(user_msg)}")

                elif field_name in ("comments", "feed"):
                    val        = change.get("value", {})
                    comment_id = val.get("id") or val.get("comment_id")
                    media_id   = val.get("media", {}).get("id") or val.get("post_id")
                    user_msg   = val.get("text") or val.get("message")
                    from_user  = val.get("from", {})
                    sender_id  = from_user.get("id")
                    print(f"[webhook] {field_name}: comment_id={comment_id} sender={sender_id} msg={repr(user_msg)}")
                    if comment_id and user_msg and sender_id:
                        await process_comment(
                            sender_id, comment_id, media_id, user_msg,
                            recipient_instagram_id=entry_id,
                        )
                    else:
                        print(f"[webhook] WARNING: incomplete comment data — "
                              f"id={comment_id} sender={sender_id} msg={repr(user_msg)}")

        elif "messaging" in entry:
            for messaging in entry["messaging"]:
                msg_data = messaging.get("message", {})
                if "message_edit" in messaging:
                    msg_data = messaging.get("message_edit", {})

                sender_id    = messaging.get("sender",    {}).get("id")
                recipient_id = messaging.get("recipient", {}).get("id") or entry_id
                user_msg     = msg_data.get("text")

                # Fetch message content from API when payload is incomplete
                if not sender_id or not user_msg:
                    mid = msg_data.get("mid")
                    print(f"[webhook] incomplete messaging payload — fetching mid={mid}")
                    _acc        = ig_model.get_by_instagram_id(recipient_id) if recipient_id else None
                    fetch_token = _acc["access_token"] if _acc else None
                    if fetch_token and mid:
                        fallback = await instagram_api.fetch_message_content(fetch_token, mid)
                        print(f"[webhook] fallback fetch result: {fallback}")
                        if fallback:
                            sender_id = sender_id or fallback.get("sender_id")
                            user_msg  = user_msg  or fallback.get("text")

                print(f"[webhook] DM via messaging: sender={sender_id} recipient={recipient_id} msg={repr(user_msg)}")
                if sender_id and recipient_id and user_msg:
                    await process_dm(sender_id, recipient_id, user_msg, entry_id=entry_id)
                else:
                    print(f"[webhook] WARNING: skipping — missing sender/message data")

    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

async def handle_test_message(
    text: str, user_id: str, sender_name: str, message_type: str,
) -> dict:
    print(f"[test] handle_test_message: user_id={user_id} type={message_type} text={repr(text)}")
    bot_reply = generate_reply(text, user_id, [], message_type)
    print(f"[test] bot reply: {repr(bot_reply)}")

    conv_id  = f"test_{user_id}_{sender_name}"
    messages = [{"role": "user", "text": text, "ts": datetime.now().isoformat()}]
    if bot_reply:
        messages.append({"role": "bot", "text": bot_reply, "ts": datetime.now().isoformat()})

    conv_model.upsert_test(
        conv_id, user_id, "test_account", sender_name,
        json.dumps(messages), datetime.now().isoformat(), 1,
    )
    return {"bot_reply": bot_reply or "No reply triggered"}


async def handle_test_comment(text: str, user_id: str) -> dict:
    print(f"[test] handle_test_comment: user_id={user_id} text={repr(text)}")

    matched_row, default_row = _find_matching_flow(text, user_id, "comment")
    effective_row = matched_row or default_row

    bot_comment_reply: Optional[str] = None
    dm_followup:       Optional[str] = None

    if effective_row:
        reply_type        = effective_row["reply_type"]
        bot_comment_reply = _get_message_content(effective_row) if reply_type in ("comment", "both") else None
        if reply_type == "both":
            dm_followup = _get_dm_step_content(effective_row) or bot_comment_reply
    else:
        print(f"[test] no matching flow for comment text={repr(text)}")

    return {
        "bot_comment_reply": bot_comment_reply,
        "dm_followup":       dm_followup,
        "status":            "simulated",
    }
