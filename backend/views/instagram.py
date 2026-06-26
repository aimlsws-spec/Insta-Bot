"""
views/instagram.py — Instagram OAuth routes and account management API.

Two routers are registered:

  api_router   prefix=/api/instagram   — JSON API (requires Bearer auth)
  auth_router  prefix=/auth/instagram  — Browser OAuth flow (no Bearer header possible)

The auth_router paths (/auth/instagram/login, /auth/instagram/callback) are what
Meta's App Dashboard must have registered as Valid OAuth Redirect URIs.
"""

import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from views.schemas  import InstagramAccountConnect
from controllers    import instagram as ig_ctrl
from controllers.instagram import OAuthError
from models         import instagram as ig_model
from core.config    import INSTAGRAM_REDIRECT_URI, OAUTH_STATE_TTL_SECONDS, FRONTEND_URL, BACKEND_URL
from core.security  import get_current_user

# ── API router — requires Bearer token ───────────────────────────────────────
router = APIRouter(prefix="/api/instagram", tags=["instagram"])

# ── Auth router — browser-facing, no Authorization header possible ────────────
auth_router = APIRouter(prefix="/auth/instagram", tags=["instagram-oauth"])


# ─────────────────────────────────────────────────────────────────────────────
# API routes — /api/instagram/*
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/connect")
async def connect(
    account_data: InstagramAccountConnect,
    user_id: str = Depends(get_current_user),
):
    return ig_ctrl.connect(
        user_id,
        account_data.instagram_id,
        account_data.access_token,
        account_data.username,
    )


@router.get("/accounts")
async def get_accounts(user_id: str = Depends(get_current_user)):
    return ig_ctrl.list_accounts(user_id)


@router.delete("/accounts/{account_id}")
async def disconnect(account_id: str, user_id: str = Depends(get_current_user)):
    return ig_ctrl.disconnect(account_id, user_id)


@router.get("/oauth/start")
async def oauth_start(user_id: str = Depends(get_current_user)):
    """
    Phase 2 entry point for SPA frontends.

    Returns {state, auth_url} — the frontend must redirect the user's browser
    to auth_url to begin the Instagram OAuth consent screen.

    The state token is single-use, DB-backed (survives server restarts),
    and expires after OAUTH_STATE_TTL_SECONDS (default 10 minutes).
    """
    if not INSTAGRAM_REDIRECT_URI:
        return JSONResponse(
            status_code=500,
            content={"error": "INSTAGRAM_REDIRECT_URI is not configured on the server"},
        )

    state    = secrets.token_urlsafe(24)
    ig_model.save_oauth_state(state, user_id)
    auth_url = ig_ctrl.build_oauth_url(state, INSTAGRAM_REDIRECT_URI)

    print(f"[oauth/start] user_id={user_id} state={state!r} auth_url={auth_url}")
    return {
        "state":    state,
        "auth_url": auth_url,
        "redirect_uri": INSTAGRAM_REDIRECT_URI,
        "expires_in_seconds": OAUTH_STATE_TTL_SECONDS,
    }


@router.get("/test-permissions")
async def test_permissions(user_id: str = Depends(get_current_user)):
    """
    Makes the three API calls Meta requires to qualify each permission for Advanced Access.

    Meta's rule: "make a successful test API call" means a real HTTP 200 from the
    Graph API using a token that has the permission. Meta's backend detects this
    automatically — there is no manual submission step for the test call itself.

    Run this endpoint AFTER completing the OAuth flow at least once with a test user.
    Each permission needs its own successful call:

      instagram_basic          → GET /{ig-user-id}?fields=id,username,name,biography
      instagram_manage_messages → GET /{ig-user-id}/conversations
      pages_show_list          → GET /me/accounts

    Returns a per-permission result so you can see exactly which calls succeed.
    """
    import httpx
    from core.config import META_API_VERSION

    accounts = ig_model.get_all_by_user(user_id)
    if not accounts:
        return {
            "error": "No Instagram account connected for this user. "
                     "Complete the OAuth flow at /auth/instagram/login first."
        }

    acc   = accounts[0]
    token = acc["access_token"]
    ig_id = acc["instagram_id"]
    _graph = f"https://graph.facebook.com/{META_API_VERSION}"

    results = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:

        # ── Test 1: instagram_basic ───────────────────────────────────────────
        # Required call: fetch the IG Business Account profile fields.
        # A 200 here qualifies instagram_basic for Advanced Access review.
        r1 = await client.get(
            f"{_graph}/{ig_id}",
            params={"fields": "id,username,name,biography,followers_count,media_count",
                    "access_token": token},
        )
        results["instagram_basic"] = {
            "endpoint":   f"GET /{ig_id}?fields=id,username,name,biography,followers_count,media_count",
            "status":     r1.status_code,
            "success":    r1.status_code == 200,
            "response":   r1.json() if r1.headers.get("content-type", "").startswith("application/json") else r1.text[:300],
            "note": (
                "PASSED — Meta will detect this call automatically. "
                "Submit for Advanced Access after this succeeds."
                if r1.status_code == 200
                else "FAILED — check token validity and account type (must be BUSINESS or CREATOR)"
            ),
        }
        print(f"[test-permissions] instagram_basic: {r1.status_code} {r1.text[:200]}")

        # ── Test 2: instagram_manage_messages ─────────────────────────────────
        # Required call: list conversations on the IG Business Account.
        # The account must have at least one DM conversation (can be a test DM to itself).
        r2 = await client.get(
            f"{_graph}/{ig_id}/conversations",
            params={"platform": "instagram", "access_token": token},
        )
        results["instagram_manage_messages"] = {
            "endpoint": f"GET /{ig_id}/conversations?platform=instagram",
            "status":   r2.status_code,
            "success":  r2.status_code == 200,
            "response": r2.json() if r2.headers.get("content-type", "").startswith("application/json") else r2.text[:300],
            "note": (
                "PASSED — this qualifies instagram_manage_messages for review."
                if r2.status_code == 200
                else (
                    "FAILED (200 OAuthException is normal if no conversations exist yet — "
                    "send yourself a DM from another account first, then retry)"
                    if r2.status_code == 400
                    else "FAILED — check token has instagram_manage_messages scope"
                )
            ),
        }
        print(f"[test-permissions] instagram_manage_messages: {r2.status_code} {r2.text[:200]}")

        # ── Test 3: pages_show_list ───────────────────────────────────────────
        # Required call: list the user's Facebook Pages.
        # Token must be a User Access Token (not a Page token) with pages_show_list.
        r3 = await client.get(
            f"{_graph}/me/accounts",
            params={"fields": "id,name,instagram_business_account",
                    "access_token": token},
        )
        results["pages_show_list"] = {
            "endpoint": "GET /me/accounts?fields=id,name,instagram_business_account",
            "status":   r3.status_code,
            "success":  r3.status_code == 200,
            "response": r3.json() if r3.headers.get("content-type", "").startswith("application/json") else r3.text[:300],
            "note": (
                "PASSED — this qualifies pages_show_list for review."
                if r3.status_code == 200
                else "FAILED — token must be a User Access Token with pages_show_list scope"
            ),
        }
        print(f"[test-permissions] pages_show_list: {r3.status_code} {r3.text[:200]}")

    all_passed  = all(v["success"] for v in results.values())
    any_passed  = any(v["success"] for v in results.values())
    return {
        "ig_account_id": ig_id,
        "ig_username":   acc.get("username", ""),
        "all_passed":    all_passed,
        "summary": (
            "All three test calls succeeded. You can now submit each permission "
            "for Advanced Access in Meta App Review."
            if all_passed else
            "Some calls failed — see per-permission details below."
        ),
        "permissions": results,
        "next_steps": [
            "1. Go to developers.facebook.com > Your App > App Review > Permissions and Features",
            "2. Find each permission (instagram_basic, instagram_manage_messages, pages_show_list)",
            "3. Click 'Request Advanced Access' — it becomes clickable after successful test calls",
            "4. Submit the review with a screen-recording demo of your app using each permission",
        ] if all_passed else [
            "Fix the failing calls above first — Meta requires a 200 response before the "
            "'Request Advanced Access' button becomes active for that permission."
        ],
    }


@router.get("/debug")
async def debug_oauth(user_id: str = Depends(get_current_user)):
    """Returns connection debug info for the current user. Tokens are masked."""
    from core.config import get_safe_debug_config
    accounts = ig_model.get_all_by_user(user_id)
    safe_accounts = []
    for a in accounts:
        row = dict(a)
        tok = row.get("access_token", "")
        row["access_token"] = tok[:8] + "..." + tok[-4:] if len(tok) > 12 else "***"
        safe_accounts.append(row)
    return {
        "user_id":         user_id,
        "accounts_in_db":  safe_accounts,
        "server_config":   get_safe_debug_config(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Browser-facing auth routes — /auth/instagram/*
# These paths MUST match Meta App > Facebook Login > Valid OAuth Redirect URIs
# ─────────────────────────────────────────────────────────────────────────────

@auth_router.get("")
async def instagram_start(
    t: str = Query(None, description="Session token from localStorage.authToken"),
):
    """
    GET /auth/instagram — direct OAuth entry point (alias for /auth/instagram/login).

    Usage:
      1. Log into the dashboard and copy your token from localStorage.authToken
      2. Visit /auth/instagram?t=<your_token>
      3. You will be redirected to the Meta consent screen

    The dashboard button calls /api/instagram/oauth/start (Bearer auth) instead,
    which returns the auth_url for the frontend to redirect to — both flows share
    the same callback at /auth/instagram/callback.
    """
    if not t:
        return RedirectResponse(url=FRONTEND_URL)

    from models.user import get_session
    session = get_session(t)
    if not session:
        print(f"[auth/instagram] invalid or expired session token t={t[:8]}...")
        return RedirectResponse(url=f"{FRONTEND_URL}/?instagram_error=invalid_or_expired_session")

    user_id = session["user_id"]

    if not INSTAGRAM_REDIRECT_URI:
        return RedirectResponse(url=f"{FRONTEND_URL}/?instagram_error=server_misconfiguration")

    state    = secrets.token_urlsafe(24)
    ig_model.save_oauth_state(state, user_id)
    auth_url = ig_ctrl.build_oauth_url(state, INSTAGRAM_REDIRECT_URI)

    print(f"[auth/instagram] user_id={user_id} state={state!r} → Meta OAuth")
    return RedirectResponse(url=auth_url)


@auth_router.get("/login")
async def instagram_login(
    request: Request,
    t: str = Query(None, description="Session token — passed as ?t=<token> for browser redirect"),
):
    """
    Phase 2 — browser-redirect entry point.

    Usage: redirect the user's browser to /auth/instagram/login?t=<session_token>
    The session token identifies the logged-in user since no Authorization header
    is possible in a browser redirect.

    For SPA frontends, prefer calling GET /api/instagram/oauth/start (Bearer auth)
    to get {state, auth_url} and then do window.location.href = auth_url instead.
    """
    if not t:
        print("[auth/login] missing session token in ?t= param")
        return RedirectResponse(url=f"{FRONTEND_URL}/?instagram_error=missing_session_token")

    from models.user import get_session
    session = get_session(t)
    if not session:
        print(f"[auth/login] invalid or expired session token t={t[:8]}...")
        return RedirectResponse(url=f"{FRONTEND_URL}/?instagram_error=invalid_or_expired_session")

    user_id = session["user_id"]

    if not INSTAGRAM_REDIRECT_URI:
        print("[auth/login] INSTAGRAM_REDIRECT_URI not configured")
        return RedirectResponse(url=f"{FRONTEND_URL}/?instagram_error=server_misconfiguration")

    state    = secrets.token_urlsafe(24)
    ig_model.save_oauth_state(state, user_id)
    auth_url = ig_ctrl.build_oauth_url(state, INSTAGRAM_REDIRECT_URI)

    print(f"[auth/login] user_id={user_id} redirecting to Meta OAuth state={state!r}")
    return RedirectResponse(url=auth_url)


@auth_router.get("/callback")
async def instagram_callback(
    request: Request,
    code:  str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_reason:      str = Query(None),
    error_description: str = Query(None),
):
    """
    Phase 3 — Meta redirects here after the user grants/denies permission.

    This path (/auth/instagram/callback) must be registered in:
      Meta App > Facebook Login > Settings > Valid OAuth Redirect URIs

    And must match INSTAGRAM_REDIRECT_URI in .env exactly.

    On success  → redirects to FRONTEND_URL/?instagram_connected=1&ig_username=@xxx
    On failure  → redirects to FRONTEND_URL/?instagram_error=<reason>
    """
    frontend_ok  = f"{BACKEND_URL}/api/instagram/accounts"
    frontend_err = f"{FRONTEND_URL}/?instagram_error="

    # ── User denied permission ────────────────────────────────────────────────
    if error:
        desc = error_description or error_reason or error
        print(f"[auth/callback] Meta returned error={error!r} reason={error_reason!r} desc={error_description!r}")
        return RedirectResponse(url=frontend_err + quote(f"meta_error:{error}:{desc}"), status_code=302)

    # ── Log every incoming callback for diagnostics ───────────────────────────
    print(f"[auth/callback] incoming — code={'YES' if code else 'MISSING'} "
          f"state={'YES (' + state[:8] + '...)' if state else 'MISSING'} "
          f"error={error!r}")

    # ── Missing parameters ────────────────────────────────────────────────────
    if not code:
        print(f"[auth/callback] FAIL: missing 'code' — Meta did not include it. "
              f"Possible causes: redirect_uri mismatch, app in wrong mode, "
              f"or user denied permission without error param.")
        return RedirectResponse(url=frontend_err + "missing_code_from_meta", status_code=302)

    if not state:
        print("[auth/callback] FAIL: 'state' param is missing from Meta's redirect. "
              "Root cause: the OAuth URL sent to Meta did not include &state=... "
              "This happens when the frontend constructs its own OAuth URL client-side "
              "instead of using the auth_url returned by /api/instagram/oauth/start.")
        return RedirectResponse(url=frontend_err + "missing_state_csrf_error", status_code=302)

    # ── CSRF / state validation ───────────────────────────────────────────────
    user_id = ig_model.pop_oauth_state(state, ttl_seconds=OAUTH_STATE_TTL_SECONDS)
    if not user_id:
        print(f"[auth/callback] FAIL: state={state!r} not found, expired, or already used. "
              f"TTL={OAUTH_STATE_TTL_SECONDS}s. "
              f"Causes: (1) state was consumed by a previous request (double-submit), "
              f"(2) state expired — user took >{OAUTH_STATE_TTL_SECONDS}s to approve, "
              f"(3) /api/instagram/oauth/start was never called before this callback.")
        return RedirectResponse(url=frontend_err + "session_expired_or_invalid_state", status_code=302)

    print(f"[auth/callback] state valid — user_id={user_id} code={code[:12]}...")

    # ── Token exchange + account link ─────────────────────────────────────────
    try:
        result   = await ig_ctrl.handle_oauth_callback(user_id, code, INSTAGRAM_REDIRECT_URI)
        username = result.get("username", "")
        acct_type = result.get("account_type", "")

        extra = ""
        if acct_type == "PERSONAL":
            extra = "&account_type=PERSONAL&warning=personal_account_limited"

        print(f"[auth/callback] SUCCESS: @{username} ({acct_type}) connected for user_id={user_id}")
        return RedirectResponse(url=f"{frontend_ok}?connected=1&ig_username={quote(username)}{extra}", status_code=302)

    except OAuthError as e:
        print(f"[auth/callback] OAuthError code={e.code!r} detail={e.detail!r}")
        return RedirectResponse(url=frontend_err + quote(f"{e.code}:{e.detail}"), status_code=302)

    except Exception as e:
        print(f"[auth/callback] Unexpected error: {type(e).__name__}: {e}")
        return RedirectResponse(url=frontend_err + "internal_server_error", status_code=302)
