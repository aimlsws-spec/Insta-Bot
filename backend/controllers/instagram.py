"""controllers/instagram.py — Instagram OAuth, account connect / list / disconnect."""

import asyncio
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from models import instagram as ig_model
from models import user as user_model
from core.config import (
    PLANS,
    INSTAGRAM_APP_ID,
    INSTAGRAM_APP_SECRET,
    INSTAGRAM_AUTH_URL,
    INSTAGRAM_SCOPES,
    META_API_VERSION,
)

# ── HTTP client settings ───────────────────────────────────────────────────────
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_RETRY_DELAYS = [1.0, 2.0, 4.0]  # seconds between retries on 5xx / network error


# ── OAuth URL builder ──────────────────────────────────────────────────────────

def build_oauth_url(state: str, redirect_uri: str, scopes: list[str] = None) -> str:
    """
    Build the Meta Facebook Login OAuth authorization URL.

    The user's browser is redirected here to begin the consent flow.
    All parameters must exactly match what is registered in the Meta App dashboard.
    """
    if not INSTAGRAM_APP_ID:
        raise HTTPException(status_code=500, detail="INSTAGRAM_APP_ID is not configured")
    if not redirect_uri:
        raise HTTPException(status_code=500, detail="INSTAGRAM_REDIRECT_URI is not configured")

    scope_list = scopes or INSTAGRAM_SCOPES
    params = {
        "client_id":     INSTAGRAM_APP_ID,
        "redirect_uri":  redirect_uri,
        "scope":         ",".join(scope_list),
        "response_type": "code",
        "state":         state,
    }
    url = f"{INSTAGRAM_AUTH_URL}?{urlencode(params)}"

    # Explicit startup-visible log — confirms correct OAuth server at call time.
    print("[oauth/build_url] ── OAuth URL breakdown ──────────────────────────")
    print(f"[oauth/build_url]   base        : {INSTAGRAM_AUTH_URL}")
    print(f"[oauth/build_url]   client_id   : {INSTAGRAM_APP_ID}")
    print(f"[oauth/build_url]   redirect_uri: {redirect_uri}")
    print(f"[oauth/build_url]   scope       : {','.join(scope_list)}")
    print(f"[oauth/build_url]   full URL    : {url}")
    print("[oauth/build_url] ────────────────────────────────────────────────")

    return url


# ── Plan enforcement ───────────────────────────────────────────────────────────

def _get_plan(user_id: str) -> dict:
    row = user_model.get_subscription_plan(user_id)
    if not row:
        return PLANS["free"]
    return PLANS.get(row["subscription_plan"], PLANS["free"])


# ── Account connect (used by both direct-connect and OAuth callback) ───────────

def connect(
    user_id: str,
    instagram_id: str,
    access_token: str,
    username: str,
    account_type: str = None,
    token_scopes: str = None,
    token_expires_at: str = None,
    facebook_page_id: str = None,
    page_access_token: str = None,
) -> dict:
    print(f"[connect] user_id={user_id} ig_id={instagram_id} username={username} "
          f"account_type={account_type} page_id={facebook_page_id} expires={token_expires_at}")

    existing = ig_model.get_by_user_and_instagram_id(user_id, instagram_id)
    if existing:
        ig_model.update_token_full(
            existing["id"], access_token, username,
            account_type=account_type,
            token_scopes=token_scopes,
            token_expires_at=token_expires_at,
            facebook_page_id=facebook_page_id,
            page_access_token=page_access_token,
        )
        print(f"[connect] updated existing account_id={existing['id']}")
        return {
            "message": "Instagram account connected successfully",
            "account_id": existing["id"],
            "instagram_id": instagram_id,
            "username": username,
            "account_type": account_type,
        }

    plan  = _get_plan(user_id)
    count = ig_model.count_by_user(user_id)
    print(f"[connect] plan={plan} existing_count={count}")
    if plan["accounts"] != -1 and count >= plan["accounts"]:
        raise HTTPException(status_code=403, detail="Account limit reached for your plan")

    account_id = str(uuid.uuid4())
    ig_model.create_full(
        account_id, user_id, instagram_id, access_token, username,
        datetime.now().isoformat(), "active",
        account_type=account_type,
        token_scopes=token_scopes,
        token_expires_at=token_expires_at,
        facebook_page_id=facebook_page_id,
        page_access_token=page_access_token,
    )
    print(f"[connect] created account_id={account_id}")
    return {
        "message": "Instagram account connected successfully",
        "account_id": account_id,
        "instagram_id": instagram_id,
        "username": username,
        "account_type": account_type,
    }


# ── HTTP helper with retry ─────────────────────────────────────────────────────

async def _get_with_retry(client: httpx.AsyncClient, url: str, label: str, **kwargs) -> httpx.Response | None:
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            resp = await client.get(url, **kwargs)
            if resp.status_code < 500:
                return resp
            print(f"[oauth/{label}] attempt {attempt} — {resp.status_code} server error: {resp.text[:200]}")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            print(f"[oauth/{label}] attempt {attempt} — {type(exc).__name__}: {exc}")
        if attempt < len(_RETRY_DELAYS):
            await asyncio.sleep(delay)
    return None


# ── Webhook subscription helper ───────────────────────────────────────────────

async def _subscribe_page_to_webhooks(
    client: httpx.AsyncClient, page_id: str, page_token: str
) -> dict:
    """
    POST /{page_id}/subscribed_apps — must be called once per user after OAuth.
    Without this, Meta will never deliver DM events to /webhook.
    Uses the Page Access Token (not the User token).

    Failure is intentionally non-fatal: the account is already persisted in the
    DB by the time this runs, so a subscription error must not roll back the
    OAuth flow or prevent /api/instagram/accounts from returning a result.

    Valid fields for v22.0 (Meta removed 'comments' from this endpoint):
      messages,messaging_postbacks,feed,mention,mention_or_tag_of_pages
    """
    # 'comments' was removed from /{page_id}/subscribed_apps in Graph API v13+.
    # Use 'feed' to capture post/comment activity at the Page level instead.
    _SUBSCRIBE_FIELDS = "messages,messaging_postbacks,feed,mention"

    _graph = f"https://graph.facebook.com/{META_API_VERSION}"
    try:
        resp = await client.post(
            f"{_graph}/{page_id}/subscribed_apps",
            params={
                "subscribed_fields": _SUBSCRIBE_FIELDS,
                "access_token":      page_token,
            },
        )
        is_json = "application/json" in resp.headers.get("content-type", "")
        result  = resp.json() if is_json else {"raw": resp.text}

        if resp.status_code == 200 and result.get("success"):
            print(
                f"[webhook_sub] OK — page_id={page_id} "
                f"fields={_SUBSCRIBE_FIELDS}"
            )
        else:
            print(
                f"[webhook_sub] WARNING — page_id={page_id} "
                f"status={resp.status_code} response={result} "
                f"(webhook events may not arrive, but account is connected)"
            )
        return result

    except Exception as exc:
        print(
            f"[webhook_sub] ERROR — page_id={page_id}: {exc} "
            f"(non-fatal: account connection continues)"
        )
        return {"success": False, "error": str(exc)}


# ── Page discovery helper ──────────────────────────────────────────────────────

# Fields verified against Graph API Explorer for Page discovery.
_PAGE_FIELDS = "id,name,instagram_business_account"
_IG_ACCOUNT_FIELDS = "id,username,name"


async def _enrich_ig_accounts(
    client: httpx.AsyncClient,
    pages: list[dict],
    access_token: str,
    graph_base: str,
) -> list[dict]:
    for page in pages:
        ig = page.get("instagram_business_account") or {}
        if not (ig.get("id") and not ig.get("username")):
            continue

        enrich_resp = await client.get(
            f"{graph_base}/{ig['id']}",
            params={
                "fields": _IG_ACCOUNT_FIELDS,
                "access_token": access_token,
            },
        )
        print(
            f"[pages_resolve] IG enrich {ig['id']} status={enrich_resp.status_code} "
            f"body={enrich_resp.text[:200]}"
        )
        if enrich_resp.status_code == 200:
            ig.update(enrich_resp.json())
            page["instagram_business_account"] = ig

    return pages


async def _resolve_pages(
    client: httpx.AsyncClient,
    access_token: str,
    graph_base: str,
) -> list[dict]:
    """
    Discover Facebook Pages with a linked Instagram Business Account.

    Priority:
      1. /me/accounts                    - standard admin pages
      2. /me/assigned_pages              - BM task-assigned pages
      3. /me/businesses                  - portfolio owner path: owned_pages + client_pages
    """
    params: dict = {"fields": _PAGE_FIELDS, "access_token": access_token}

    resp = await _get_with_retry(client, f"{graph_base}/me/accounts", "pages_1", params=params)
    if resp and resp.status_code == 200:
        pages: list[dict] = resp.json().get("data", [])
        if pages:
            print(f"[pages_resolve] me/accounts -> {len(pages)} page(s); stopping fallback chain")
            return await _enrich_ig_accounts(client, pages, access_token, graph_base)
        print("[pages_resolve] me/accounts returned [] - trying me/assigned_pages")
    else:
        status = resp.status_code if resp else "no_response"
        print(f"[pages_resolve] me/accounts failed (status={status}) - trying me/assigned_pages")

    resp = await _get_with_retry(client, f"{graph_base}/me/assigned_pages", "pages_2", params=params)
    if resp and resp.status_code == 200:
        pages = resp.json().get("data", [])
        if pages:
            print(f"[pages_resolve] me/assigned_pages -> {len(pages)} page(s); stopping fallback chain")
            return await _enrich_ig_accounts(client, pages, access_token, graph_base)
        print("[pages_resolve] me/assigned_pages returned [] - trying me/businesses")
    else:
        status = resp.status_code if resp else "no_response"
        print(f"[pages_resolve] me/assigned_pages failed (status={status}) - trying me/businesses")

    biz_resp = await _get_with_retry(
        client,
        f"{graph_base}/me/businesses",
        "pages_3_biz",
        params={"fields": "id,name", "access_token": access_token},
    )
    if not (biz_resp and biz_resp.status_code == 200):
        status = biz_resp.status_code if biz_resp else "no_response"
        print(f"[pages_resolve] me/businesses failed (status={status}) - all paths exhausted")
        return []

    businesses: list[dict] = biz_resp.json().get("data", [])
    print(f"[pages_resolve] me/businesses -> {len(businesses)} business portfolio(s)")

    all_pages: list[dict] = []
    for biz in businesses:
        biz_id: str = biz["id"]
        biz_name: str = biz.get("name", biz_id)
        for sub in ("owned_pages", "client_pages"):
            r = await _get_with_retry(
                client,
                f"{graph_base}/{biz_id}/{sub}",
                f"pages_3_{sub}",
                params=params,
            )
            if r and r.status_code == 200:
                batch: list[dict] = r.json().get("data", [])
                print(f"[pages_resolve]   {biz_name}/{sub} -> {len(batch)} page(s)")
                all_pages.extend(await _enrich_ig_accounts(client, batch, access_token, graph_base))
            else:
                status = r.status_code if r else "no_response"
                print(f"[pages_resolve]   {biz_name}/{sub} failed (status={status})")

    print(f"[pages_resolve] businesses fallback total -> {len(all_pages)} page(s)")
    return all_pages

# ── OAuth callback handler ─────────────────────────────────────────────────────

class OAuthError(Exception):
    """Raised for recoverable OAuth failures that should redirect back to the frontend."""
    def __init__(self, code: str, detail: str):
        self.code   = code
        self.detail = detail
        super().__init__(detail)


async def handle_oauth_callback(user_id: str, code: str, redirect_uri: str) -> dict:
    """
    Facebook Login → Instagram Business Account OAuth flow.

    Authorization URL: https://www.facebook.com/{version}/dialog/oauth
    This flow is required for Business/Creator accounts with instagram_manage_messages.

    Step 1: Exchange code → short-lived Facebook User Access Token (1–2 hours)
            Endpoint: GET graph.facebook.com/{version}/oauth/access_token
    Step 2: Exchange short-lived token → long-lived token (60 days)
            Endpoint: GET graph.facebook.com/{version}/oauth/access_token?grant_type=fb_exchange_token
    Step 3: Discover linked Instagram Business Account via Facebook Pages
            Endpoint: GET graph.facebook.com/{version}/me/accounts
    Step 4: Persist account in DB

    Raises OAuthError on any unrecoverable failure.
    """
    _graph = f"https://graph.facebook.com/{META_API_VERSION}"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:

        # ── Debug: verify exact values reaching the token exchange ────────────
        _app_id_clean  = (INSTAGRAM_APP_ID  or "").strip()
        _secret_clean  = (INSTAGRAM_APP_SECRET or "").strip()
        _redirect_clean = (redirect_uri or "").strip()
        print(
            f"[oauth/debug] ── token-exchange pre-flight ──────────────────────\n"
            f"[oauth/debug]   app_id       = {_app_id_clean!r}  (len={len(_app_id_clean)})\n"
            f"[oauth/debug]   secret_set   = {bool(_secret_clean)}  secret_len={len(_secret_clean)}\n"
            f"[oauth/debug]   redirect_uri = {_redirect_clean!r}\n"
            f"[oauth/debug]   code_prefix  = {code[:12]!r}...\n"
            f"[oauth/debug]   api_version  = {META_API_VERSION}\n"
            f"[oauth/debug] ─────────────────────────────────────────────────────"
        )

        if not _app_id_clean:
            raise OAuthError("bad_config", "INSTAGRAM_APP_ID is empty — check .env file")
        if not _secret_clean:
            raise OAuthError("bad_config", "INSTAGRAM_APP_SECRET is empty — check .env file")

        # ── Step 1: Code → short-lived Facebook User Access Token ────────────
        # Meta recommends POST (form body) for the code-exchange step.
        # Using GET with query params can trigger error_subcode=1349040 on
        # newer app configurations even though GET is technically documented.
        token_exchange_url = f"{_graph}/oauth/access_token"
        try:
            resp = await client.post(
                token_exchange_url,
                data={
                    "client_id":     _app_id_clean,
                    "client_secret": _secret_clean,
                    "redirect_uri":  _redirect_clean,
                    "code":          code,
                    "grant_type":    "authorization_code",
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise OAuthError("network_error", f"Failed to reach graph.facebook.com: {exc}")

        print(f"[oauth/step1] POST {token_exchange_url}")
        print(f"[oauth/step1] status={resp.status_code} body={resp.text[:500]}")

        if resp.status_code != 200:
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            err_obj  = body.get("error", {})
            err_msg  = err_obj.get("message") or body.get("error_description") or resp.text
            err_sub  = err_obj.get("error_subcode", "")
            hint = ""
            if err_sub == 1349040:
                hint = (
                    " | HINT 1349040: verify (a) Facebook Login product is added to the app "
                    "and 'Web OAuth Login' is ON, (b) all requested scopes are enabled under "
                    "App Review → Permissions and Features, (c) redirect URI in Facebook Login "
                    "settings exactly matches INSTAGRAM_REDIRECT_URI"
                )
            raise OAuthError("code_exchange_failed", f"Meta rejected code: {err_msg}{hint}")

        token_data        = resp.json()
        short_lived_token = token_data.get("access_token", "")
        if not short_lived_token:
            raise OAuthError("code_exchange_failed", f"No access_token in response: {token_data}")

        print(f"[oauth/step1] SUCCESS: short-lived token obtained")

        # ── Step 2: Short-lived → long-lived Facebook User Access Token (60d) ─
        # grant_type=fb_exchange_token is Facebook's equivalent of Instagram's ig_exchange_token.
        access_token     = short_lived_token
        token_expires_at = None

        lt_resp = await _get_with_retry(
            client,
            f"{_graph}/oauth/access_token",
            "step2_long_lived",
            params={
                "grant_type":        "fb_exchange_token",
                "client_id":         INSTAGRAM_APP_ID,
                "client_secret":     INSTAGRAM_APP_SECRET,
                "fb_exchange_token": short_lived_token,
            },
        )
        print(f"[oauth/step2] status={lt_resp.status_code if lt_resp else 'None'} "
              f"body={lt_resp.text[:300] if lt_resp else 'N/A'}")

        if lt_resp and lt_resp.status_code == 200:
            lt_data          = lt_resp.json()
            access_token     = lt_data.get("access_token", short_lived_token)
            expires_in       = lt_data.get("expires_in", 0)  # ~5,183,944s ≈ 60 days
            if expires_in:
                token_expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
            print(f"[oauth/step2] SUCCESS: long-lived token expires_in={expires_in}s expires_at={token_expires_at}")
        else:
            print("[oauth/step2] WARNING: long-lived exchange failed — using short-lived token (2h max)")
            token_expires_at = (datetime.now() + timedelta(hours=2)).isoformat()

        # ── Step 3: Discover Instagram Business Account via Facebook Pages ────
        #
        # _resolve_pages tries three endpoints in order:
        #   1. /me/accounts        — standard admin pages
        #   2. /me/assigned_pages  — Business Manager task-assigned pages
        #   3. /me/businesses      — portfolio owner path
        # This handles tokens with granular BM permissions that return [] from
        # /me/accounts silently (confirmed via Meta Graph API Explorer).
        pages: list[dict] = await _resolve_pages(client, access_token, _graph)
        print(f"[oauth/step3] total pages resolved: {len(pages)}")

        if not pages:
            raise OAuthError(
                "pages_fetch_failed",
                "No Facebook Pages found via me/accounts, me/assigned_pages, or "
                "me/businesses. Ensure pages_show_list was granted and this account "
                "manages at least one Page linked to an Instagram Business Account.",
            )

        ig_account_id       = None
        ig_username         = ""
        account_type        = None
        facebook_page_id    = None
        facebook_page_token = None

        for page in pages:
            ig = page.get("instagram_business_account")
            if ig and ig.get("id"):
                ig_account_id       = ig["id"]
                ig_username         = ig.get("username", "")
                account_type        = ig.get("account_type", "BUSINESS")
                facebook_page_id    = page.get("id", "")
                facebook_page_token = page.get("access_token", "")
                print(
                    f"[oauth/step3] SUCCESS: page='{page.get('name')}' (page_id={facebook_page_id}) "
                    f"→ @{ig_username} (ig_id={ig_account_id} type={account_type})"
                )
                break

        if not ig_account_id:
            raise OAuthError(
                "no_ig_business_account",
                "No Instagram Business or Creator account found linked to your Facebook Pages. "
                "Open Instagram app → Settings → Account → Switch to Professional Account, "
                "then connect that Instagram account to a Facebook Page.",
            )

        # ── Step 4: Persist ───────────────────────────────────────────────────
        scope_str = ",".join(INSTAGRAM_SCOPES)
        result    = connect(
            user_id, ig_account_id, access_token, ig_username,
            account_type=account_type,
            token_scopes=scope_str,
            token_expires_at=token_expires_at,
            facebook_page_id=facebook_page_id,
            page_access_token=facebook_page_token,
        )

        # ── Step 5: Subscribe Facebook Page to webhook events ─────────────────
        # Required per-user so Meta delivers DM + comment events to /webhook.
        if facebook_page_id and facebook_page_token:
            await _subscribe_page_to_webhooks(client, facebook_page_id, facebook_page_token)

        return result


# ── Token refresh (call before token_expires_at) ──────────────────────────────

async def refresh_long_lived_token(account_id: str, current_token: str) -> bool:
    """
    Refresh a long-lived Facebook User Access Token (60-day window reset).

    For tokens obtained via Facebook Login (www.facebook.com/dialog/oauth),
    refresh uses fb_exchange_token — NOT ig_refresh_token, which only works
    for tokens from the deprecated Instagram Login product.

    Must be called while the current token is still valid.
    """
    _graph = f"https://graph.facebook.com/{META_API_VERSION}"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await _get_with_retry(
            client,
            f"{_graph}/oauth/access_token",
            "token_refresh",
            params={
                "grant_type":        "fb_exchange_token",
                "client_id":         INSTAGRAM_APP_ID,
                "client_secret":     INSTAGRAM_APP_SECRET,
                "fb_exchange_token": current_token,
            },
        )
        if resp and resp.status_code == 200:
            data       = resp.json()
            new_token  = data.get("access_token", current_token)
            expires_in = data.get("expires_in", 0)
            expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat() if expires_in else None
            ig_model.update_token_full(account_id, new_token, "", token_expires_at=expires_at)
            print(f"[token_refresh] SUCCESS: account_id={account_id} new_expires_at={expires_at}")
            return True

        print(f"[token_refresh] FAILED: account_id={account_id} "
              f"status={resp.status_code if resp else 'None'} "
              f"body={resp.text[:200] if resp else 'N/A'}")
        return False


# ── CRUD ───────────────────────────────────────────────────────────────────────

def list_accounts(user_id: str) -> dict:
    accounts = []
    for row in ig_model.get_all_by_user(user_id):
        a = dict(row)
        # Mask token in list response
        tok = a.get("access_token", "")
        a["access_token"] = tok[:6] + "..." if len(tok) > 6 else "***"
        accounts.append(a)
    return {"accounts": accounts}


def disconnect(account_id: str, user_id: str) -> dict:
    ig_model.delete(account_id, user_id)
    return {"message": "Deleted"}
