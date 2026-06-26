"""views/webhook.py — /api/webhook/* routes (Instagram webhook verification + receive)."""

import hashlib
import hmac
import json
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from controllers import webhook as webhook_ctrl
from core.config import INSTAGRAM_APP_SECRET, META_API_VERSION, PAGE_ACCESS_TOKEN, WEBHOOK_VERIFY_TOKEN

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

# ── Meta-required top-level /webhook routes ───────────────────────────────────
# Meta sends webhooks to exactly /webhook (no prefix).
# This router has no prefix so GET /webhook and POST /webhook are reachable.
meta_router = APIRouter(tags=["webhook"])


def _verify_meta_signature(body: bytes, sig_header: str) -> None:
    """Verify the X-Hub-Signature-256 HMAC sent by Meta.

    WHY raw bytes matter
    --------------------
    Meta computes the signature over the exact bytes it transmitted.
    Calling `await request.json()` first parses the body into a Python dict —
    re-serialising that dict with json.dumps() produces different whitespace or
    key ordering, so the HMAC never matches.  Always pass the raw
    `await request.body()` result here: no decoding, no re-encoding.

    Verification steps (order matters)
    -----------------------------------
    1. Encode the app secret to UTF-8 bytes (HMAC key).
    2. Strip the "sha256=" prefix from the header → plain received hex.
    3. Compute HMAC-SHA256 over the raw body bytes → plain computed hex.
    4. Compare the two hex strings with hmac.compare_digest (constant-time).
    """
    if not INSTAGRAM_APP_SECRET:
        return

    if not sig_header:
        print("[/webhook POST] WARNING: X-Hub-Signature-256 header missing - allowing (dev mode)")
        return

    # ── Step 1: encode the secret key ────────────────────────────────────────
    # .strip() removes any trailing newline/space that dotenv leaves in the
    # value — a single invisible byte changes every HMAC output.
    # The key must be bytes; encode to UTF-8 so the HMAC function accepts it.
    secret_bytes: bytes = INSTAGRAM_APP_SECRET.strip().encode("utf-8")

    # ── Step 2: extract the hex digest from the header ────────────────────────
    # Meta sends:  X-Hub-Signature-256: sha256=<64 lowercase hex chars>
    # Strip outer whitespace first (guards against HTTP proxy padding), then
    # remove the "sha256=" prefix so we compare only the hex part.
    # Normalise to lowercase in case a proxy uppercases the hex.
    raw_header: str = sig_header.strip()
    if not raw_header.startswith("sha256="):
        print(f"[/webhook POST] SIGNATURE ERROR: header missing sha256= prefix: {raw_header!r}")
        raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256")
    received_hex: str = raw_header.split("=", 1)[1].lower()

    # ── Step 3: compute the expected HMAC-SHA256 hex digest ───────────────────
    # hmac.new(key, msg, digestmod) — all three args required in Python 3.
    # hashlib.sha256 is passed as a callable (not an instance), which is the
    # correct, modern form.  .hexdigest() returns a lowercase hex string.
    # body must be the raw bytes from `await request.body()` — see docstring.
    computed_hex: str = hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()

    # ── Step 4: constant-time comparison of the two hex strings ──────────────
    # hmac.compare_digest prevents timing attacks: it always takes the same
    # time regardless of where the strings diverge — never use == here.
    # Both inputs are plain hex strings (no "sha256=" prefix) — apples to apples.
    if not hmac.compare_digest(received_hex, computed_hex):
        print(
            f"[/webhook POST] SIGNATURE MISMATCH\n"
            f"  received hex : {received_hex[:16]}...\n"
            f"  computed hex : {computed_hex[:16]}...\n"
            f"  body length  : {len(body)} bytes\n"
            f"  secret length: {len(secret_bytes)} bytes"
        )
        raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256")


def _extract_messaging_events(data: dict) -> list[dict]:
    events: list[dict] = []
    for entry in data.get("entry", []):
        for messaging in entry.get("messaging", []):
            message = messaging.get("message") or {}
            sender_id = messaging.get("sender", {}).get("id")
            text = message.get("text")

            if message.get("is_echo"):
                print(f"[/webhook POST] ignoring echo message from sender={sender_id}")
                continue

            if sender_id and text:
                events.append({"sender_id": sender_id, "text": text})
            else:
                print(
                    "[/webhook POST] skipping non-text/incomplete messaging event "
                    f"sender={sender_id} text_present={bool(text)}"
                )

    return events


async def _send_auto_reply(sender_id: str, text: str) -> dict:
    if not PAGE_ACCESS_TOKEN:
        print("[/webhook POST] PAGE_ACCESS_TOKEN is not configured; cannot send auto-reply")
        return {"sent": False, "error": "missing_page_access_token"}

    url = f"https://graph.facebook.com/{META_API_VERSION}/me/messages"
    payload = {
        "recipient": {"id": sender_id},
        "message": {"text": text},
    }
    headers = {"Authorization": f"Bearer {PAGE_ACCESS_TOKEN}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        print(f"[/webhook POST] auto-reply failed status={resp.status_code} body={resp.text[:300]}")
        return {"sent": False, "status_code": resp.status_code, "response": resp.text[:300]}

    print(f"[/webhook POST] auto-reply sent to sender={sender_id}")
    return {"sent": True, "status_code": resp.status_code}


async def _handle_auto_replies(data: dict) -> list[dict]:
    results: list[dict] = []
    for event in _extract_messaging_events(data):
        incoming_text = event["text"].strip()
        reply_text = (
            "Hi there! How can I help you today?"
            if incoming_text.lower() == "hello"
            else "Thanks for your message!"
        )
        send_result = await _send_auto_reply(event["sender_id"], reply_text)
        results.append({
            "sender_id": event["sender_id"],
            "incoming_text": incoming_text,
            "reply_text": reply_text,
            "send_result": send_result,
        })

    return results


@meta_router.get("/webhook", response_class=PlainTextResponse)
async def meta_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """
    Meta webhook verification handshake.
    Must echo hub.challenge as plain text with HTTP 200.
    """
    # Get and clean the verify token from query params
    token = (hub_verify_token or "").strip()
    expected = WEBHOOK_VERIFY_TOKEN.strip()

    # Log the verification attempt (avoid logging the actual token for security)
    print(f"[/webhook GET] mode={hub_mode!r} token_provided={bool(token)} challenge={hub_challenge!r}")

    # Verify the mode and token
    if hub_mode == "subscribe" and token == expected:
        print("[/webhook GET] verification SUCCESS")
        return PlainTextResponse(content=hub_challenge or "")

    # Log why verification failed
    print(f"[/webhook GET] verification FAILED — mode={hub_mode!r}, token_match={token == expected}")
    raise HTTPException(status_code=403, detail="Forbidden")


@meta_router.post("/webhook")
async def meta_receive(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
):
    """Receives live Instagram/Facebook webhook events with HMAC-SHA256 signature verification."""
    try:
        # Step 1 — Read raw bytes FIRST.
        # request.body() returns the unmodified bytes exactly as Meta sent them.
        # These bytes are what Meta's HMAC was computed over.  Do NOT call
        # request.json() before this — JSON parsing is done below, only after
        # the signature is confirmed valid.
        body: bytes = await request.body()
        print(f"[/webhook POST] body={body[:300]}", flush=True)

        # Step 2 — Verify signature against the raw bytes.
        # FastAPI injects x_hub_signature_256 directly from the header; no manual
        # request.headers.get() needed.
        _verify_meta_signature(body, x_hub_signature_256 or "")

        # Step 3 — Signature passed; safe to parse JSON now.
        data = json.loads(body.decode("utf-8"))
        print(f"[/webhook POST] --- EVENT RECEIVED ---")
        print(f"[/webhook POST] body={data}", flush=True)

        auto_reply_results = await _handle_auto_replies(data)
        if auto_reply_results:
            return {"status": "ok", "auto_replies": auto_reply_results}

        result = await webhook_ctrl.handle_webhook(data)
        return result if result else {"status": "ok"}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except HTTPException:
        # Re-raise HTTP exceptions (like 403 from signature validation) to preserve status code
        raise
    except Exception as e:
        print(f"[/webhook POST] Unexpected error: {e}")
        return {"status": "error", "detail": str(e)}


# ── Existing webhook routes (keep for backward compatibility) ─────────────────
@router.get("/instagram")
async def verify(request: Request):
    """
    Meta sends GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    We must echo back hub.challenge as plain text with HTTP 200.
    Any other response causes Meta to mark verification as failed.
    """
    mode = request.query_params.get("hub.mode")
    token = (request.query_params.get("hub.verify_token") or "").strip()
    challenge = request.query_params.get("hub.challenge", "")
    expected = WEBHOOK_VERIFY_TOKEN.strip()

    print(f"[webhook/verify] mode={mode!r} token={token!r} expected={expected!r} challenge={challenge!r}")

    if not expected:
        print("[webhook/verify] FATAL: WEBHOOK_VERIFY_TOKEN is not set in .env")
        raise HTTPException(status_code=500, detail="Server misconfiguration: WEBHOOK_VERIFY_TOKEN missing")

    if mode == "subscribe" and token == expected:
        print("[webhook/verify] SUCCESS: challenge accepted")
        return PlainTextResponse(content=challenge)

    print(f"[webhook/verify] FAILED: mode={mode!r} token_match={token == expected}")
    raise HTTPException(status_code=403, detail="Webhook verification failed: token mismatch")


@router.post("/instagram")
async def receive(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
):
    """
    Meta sends POST with JSON payload signed with X-Hub-Signature-256.
    We verify the HMAC-SHA256 signature before processing.
    """
    try:
        # Step 1 — Raw bytes first; signature verification requires the exact
        # bytes Meta transmitted.  Parsing JSON first and re-serialising would
        # produce a different byte sequence and a mismatched HMAC.
        body: bytes = await request.body()

        # Step 2 — Verify before touching the payload.
        _verify_meta_signature(body, x_hub_signature_256 or "")

        # Step 3 — Signature valid; now safe to decode and parse.
        decoded_body = body.decode("utf-8")
        print(f"\n[webhook/receive] --- EVENT RECEIVED ---")
        print(f"[webhook/receive] body={decoded_body[:500]}", flush=True)

        data = json.loads(decoded_body)
        auto_reply_results = await _handle_auto_replies(data)
        if auto_reply_results:
            return {"status": "ok", "auto_replies": auto_reply_results}

        result = await webhook_ctrl.handle_webhook(data)
        return result if result else {"status": "ok"}

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        print(f"[webhook/receive] JSON parse error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        print(f"[webhook/receive] Unexpected error: {e}")
        return {"status": "error", "detail": str(e)}
