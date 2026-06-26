"""
services/instagram_api.py
All outbound calls to the Meta Graph API.
No DB access, no business logic — pure HTTP integration.
"""

import asyncio
import httpx

from core.config import META_API_VERSION

_GRAPH      = f"https://graph.facebook.com/{META_API_VERSION}"
_TIMEOUT    = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_MAX_RETRY  = 3
_BACKOFF    = [1, 2, 4]
_RETRY_5XX  = {500, 502, 503, 504}
_NO_RETRY   = {400, 401, 403, 404}


async def _request(method: str, url: str, label: str, **kwargs) -> httpx.Response | None:
    kwargs.setdefault("timeout", _TIMEOUT)
    async with httpx.AsyncClient() as client:
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code in _NO_RETRY:
                    print(f"[meta] {label} attempt {attempt} — {resp.status_code} (no retry): {resp.text[:200]}")
                    return resp
                if resp.status_code in (200, 201):
                    return resp
                if resp.status_code == 429 or resp.status_code in _RETRY_5XX:
                    print(f"[meta] {label} attempt {attempt} — {resp.status_code}, retrying")
                    if attempt < _MAX_RETRY:
                        await asyncio.sleep(_BACKOFF[attempt - 1])
                    continue
                return resp
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                print(f"[meta] {label} attempt {attempt} — {type(exc).__name__}, retrying")
                if attempt < _MAX_RETRY:
                    await asyncio.sleep(_BACKOFF[attempt - 1])
        print(f"[meta] {label} — all {_MAX_RETRY} attempts failed")
        return None


async def send_message(token: str, ig_account_id: str, recipient_id: str, message: str) -> None:
    """Send a DM via the Instagram Business Messaging API."""
    url     = f"{_GRAPH}/{ig_account_id}/messages"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": message}}
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[send_message] ig_account={ig_account_id} -> recipient={recipient_id}: {message!r}")
    resp = await _request("POST", url, f"send_message:{recipient_id}", json=payload, headers=headers)
    if resp:
        print(f"[send_message] {resp.status_code}: {resp.text}")


async def send_comment_reply(token: str, comment_id: str, message: str) -> None:
    """Reply to an Instagram comment."""
    url     = f"{_GRAPH}/{comment_id}/replies"
    payload = {"message": message}
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[send_comment_reply] comment={comment_id}: {message!r}")
    resp = await _request("POST", url, f"send_comment_reply:{comment_id}", json=payload, headers=headers)
    if resp:
        print(f"[send_comment_reply] {resp.status_code}: {resp.text}")


async def fetch_message_content(token: str, mid: str) -> dict | None:
    """Fetch full message payload by message ID (used when webhook payload is incomplete)."""
    url  = f"{_GRAPH}/{mid}"
    # Token in Authorization header — never in query string (visible in server logs).
    resp = await _request(
        "GET", url, f"fetch_message:{mid}",
        params={"fields": "id,message,from"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp and resp.status_code == 200:
        d = resp.json()
        return {"text": d.get("message"), "sender_id": d.get("from", {}).get("id")}
    if resp:
        print(f"[fetch_message] failed {resp.status_code}: {resp.text[:200]}")
    return None
