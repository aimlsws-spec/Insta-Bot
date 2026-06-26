"""
core/config.py
Application-wide constants and environment config.
No imports from other project layers — only stdlib + dotenv.
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

# ── Core app ──────────────────────────────────────────────────────────────────
APP_PORT: int = int(os.getenv("APP_PORT", "8001"))
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL: str  = os.getenv("BACKEND_URL", "http://localhost:8001")

# ── Meta / Instagram credentials ─────────────────────────────────────────────
# Both FACEBOOK_APP_ID and INSTAGRAM_APP_ID should be the SAME Meta App ID.
# INSTAGRAM_APP_SECRET takes priority; falls back to FACEBOOK_APP_SECRET.
# These must BOTH equal the single App Secret from Meta's App dashboard.
INSTAGRAM_APP_ID: str     = os.getenv("INSTAGRAM_APP_ID", "") or os.getenv("FACEBOOK_APP_ID", "")
INSTAGRAM_APP_SECRET: str = os.getenv("INSTAGRAM_APP_SECRET", "") or os.getenv("FACEBOOK_APP_SECRET", "")

# ── Webhook ───────────────────────────────────────────────────────────────────
WEBHOOK_VERIFY_TOKEN: str = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
PAGE_ACCESS_TOKEN: str = (
    os.getenv("PAGE_ACCESS_TOKEN", "")
    or os.getenv("INSTAGRAM_PAGE_ACCESS_TOKEN", "")
    or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
)

# ── Dev: webhook test ID mapping ─────────────────────────────────────────────
# Meta's "Send Test" button uses dummy recipient IDs that don't exist in the DB.
# WEBHOOK_TEST_ID_MAP lets you redirect them to real instagram_ids without
# touching production code.  Format: "fake_id:real_id[,fake_id2:real_id2]"
# Empty in production — the lookup returns the original ID unchanged.
def _parse_test_id_map() -> dict:
    raw = os.getenv("WEBHOOK_TEST_ID_MAP", "").strip()
    if not raw:
        return {}
    result: dict = {}
    for pair in raw.split(","):
        parts = pair.strip().split(":", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            result[parts[0].strip()] = parts[1].strip()
    return result

WEBHOOK_TEST_ID_MAP: dict = _parse_test_id_map()

# ── OAuth redirect URIs ───────────────────────────────────────────────────────
# These MUST exactly match what is registered in Meta App > Facebook Login >
# Settings > Valid OAuth Redirect URIs — character for character.
INSTAGRAM_REDIRECT_URI: str = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    f"{BACKEND_URL}/auth/instagram/callback",
)
FACEBOOK_REDIRECT_URI: str = os.getenv(
    "FACEBOOK_REDIRECT_URI",
    f"{BACKEND_URL}/auth/facebook/callback",
)

# ── Meta Graph API version ────────────────────────────────────────────────────
# Single place to bump the API version across auth + Graph API calls.
META_API_VERSION: str = "v22.0"

# ── Instagram OAuth constants ─────────────────────────────────────────────────
# Facebook Login OAuth dialog — required for Business/Creator accounts that
# need instagram_manage_messages and pages_show_list.
# The code exchanged here must be redeemed at graph.facebook.com (not api.instagram.com).
INSTAGRAM_AUTH_URL: str = f"https://www.facebook.com/{META_API_VERSION}/dialog/oauth"

# Scopes for Instagram Business Account discovery via Facebook Login.
# business_management → required for /me/assigned_pages and /me/businesses on
#                       tokens scoped to a Meta Business Suite portfolio.
#                       Without it, those endpoints return HTTP 400 for
#                       granular BM-managed tokens even when pages_show_list
#                       is present.  Needs App Review before going Live;
#                       works for all app roles in Development mode.
INSTAGRAM_SCOPES: list[str] = [
    "instagram_basic",
    "instagram_manage_messages",  # ← ADDED FOR INSTAGRAM DM SUPPORT
    "pages_show_list",
    "pages_read_engagement",
    "business_management"
]

# How long (seconds) an OAuth state token is valid before it expires.
OAUTH_STATE_TTL_SECONDS: int = int(os.getenv("OAUTH_STATE_TTL_SECONDS", "600"))  # 10 min

# ── Plans ─────────────────────────────────────────────────────────────────────
PLANS: dict = {
    "free":       {"accounts": 1,  "broadcasts": 1},
    "starter":    {"accounts": 3,  "broadcasts": 10},
    "pro":        {"accounts": 10, "broadcasts": 100},
    "enterprise": {"accounts": -1, "broadcasts": -1},
}

# ── Required env vars — missing any of these will abort startup ───────────────
_REQUIRED = [
    "INSTAGRAM_APP_ID",
    "INSTAGRAM_APP_SECRET",
    "WEBHOOK_VERIFY_TOKEN",
    "INSTAGRAM_REDIRECT_URI",
    "DB_HOST",
    "DB_NAME",
]


def validate_env() -> None:
    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        print(f"[config] FATAL: missing required env vars: {missing}", file=sys.stderr)
        sys.exit(1)
    _warn_secret_mismatch()
    _log_oauth_config()


def _log_oauth_config() -> None:
    """Print OAuth configuration at startup so mis-configuration is immediately visible."""
    correct = f"https://www.facebook.com/{META_API_VERSION}/dialog/oauth"
    wrong   = "https://api.instagram.com/oauth/authorize"

    print("[config] ── OAuth configuration ─────────────────────────────────")
    print(f"[config]   META_API_VERSION    : {META_API_VERSION}")
    print(f"[config]   INSTAGRAM_AUTH_URL  : {INSTAGRAM_AUTH_URL}")
    print(f"[config]   INSTAGRAM_APP_ID    : {INSTAGRAM_APP_ID or 'NOT SET'}")
    print(f"[config]   INSTAGRAM_REDIRECT_URI: {INSTAGRAM_REDIRECT_URI or 'NOT SET'}")
    print(f"[config]   INSTAGRAM_SCOPES    : {','.join(INSTAGRAM_SCOPES)}")

    if INSTAGRAM_AUTH_URL == correct:
        print("[config]   AUTH_URL CHECK      : OK — Facebook Login (correct for Business accounts)")
    elif INSTAGRAM_AUTH_URL == wrong:
        print("[config]   AUTH_URL CHECK      : WRONG — still pointing at api.instagram.com", file=sys.stderr)
        print("[config]   Fix: set INSTAGRAM_AUTH_URL in core/config.py to:", file=sys.stderr)
        print(f"[config]     {correct}", file=sys.stderr)
    else:
        print(f"[config]   AUTH_URL CHECK      : CUSTOM — verify this is intentional")
    print("[config] ────────────────────────────────────────────────────────")


def _warn_secret_mismatch() -> None:
    fb_secret = os.getenv("FACEBOOK_APP_SECRET", "")
    ig_secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    if fb_secret and ig_secret and fb_secret != ig_secret:
        print(
            "[config] WARNING: FACEBOOK_APP_SECRET and INSTAGRAM_APP_SECRET differ. "
            "They must both equal the single App Secret from Meta's App dashboard "
            "(developers.facebook.com > App Settings > Basic > App Secret). "
            "Set both to the same value or remove the duplicate.",
            file=sys.stderr,
        )


def get_safe_debug_config() -> dict:
    """Returns config state with secrets masked — safe to return in API responses."""
    def _mask(v: str) -> str:
        if not v:
            return "NOT SET"
        if len(v) <= 8:
            return "***"
        return v[:4] + "..." + v[-4:]

    return {
        "APP_PORT": APP_PORT,
        "BACKEND_URL": BACKEND_URL,
        "FRONTEND_URL": FRONTEND_URL,
        "INSTAGRAM_APP_ID": INSTAGRAM_APP_ID or "NOT SET",
        "INSTAGRAM_APP_SECRET": _mask(INSTAGRAM_APP_SECRET),
        "FACEBOOK_APP_SECRET": _mask(os.getenv("FACEBOOK_APP_SECRET", "")),
        "PAGE_ACCESS_TOKEN": _mask(PAGE_ACCESS_TOKEN),
        "secrets_match": (
            os.getenv("FACEBOOK_APP_SECRET", "") == os.getenv("INSTAGRAM_APP_SECRET", "")
            if os.getenv("FACEBOOK_APP_SECRET") and os.getenv("INSTAGRAM_APP_SECRET")
            else "N/A (only one set)"
        ),
        "WEBHOOK_VERIFY_TOKEN": _mask(WEBHOOK_VERIFY_TOKEN),
        "INSTAGRAM_REDIRECT_URI": INSTAGRAM_REDIRECT_URI or "NOT SET",
        "FACEBOOK_REDIRECT_URI": FACEBOOK_REDIRECT_URI or "NOT SET",
        "DB_HOST": os.getenv("DB_HOST", "NOT SET"),
        "DB_NAME": os.getenv("DB_NAME", "NOT SET"),
    }
