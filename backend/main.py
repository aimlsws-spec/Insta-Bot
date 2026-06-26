"""
main.py — application entry point (thin app factory)

Responsibilities:
  • Create the FastAPI app instance
  • Register middleware
  • Mount all routers
  • Call init_db() at startup

All business logic, DB queries, and external API calls live in their
respective MVC layers (controllers/, models/, services/).
"""

import sys

print("\n--- SERVER VERSION 5.0 STARTING ---\n")

# Fix Windows Console Emoji Crash
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import asyncio

import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from core.db import init_db
from core.rate_limit import RateLimitMiddleware
from core.config import validate_env, get_safe_debug_config, APP_PORT
from services.broadcast_worker import run_worker

# ── Routers ───────────────────────────────────────────────────────────────────
from views.auth          import router as auth_router
from views.instagram     import router as instagram_router, auth_router as instagram_auth_router
from views.flows         import router as flows_router
from views.templates     import router as templates_router
from views.broadcasts    import router as broadcasts_router
from views.conversations import router as conversations_router
from views.analytics     import router as analytics_router
from views.webhook       import router as webhook_router, meta_router as meta_webhook_router
from views.test          import router as test_router

# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(title="Instagram Bot Platform - ManyChat Alternative", version="3.0.0")

# Trust X-Forwarded-* headers from ngrok / reverse proxies so that
# request.base_url and request.url return the public HTTPS URL, not localhost.
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
# trusted_hosts — renamed from 'trusted' in uvicorn 0.20. Accepts str or list[str].
# "127.0.0.1" is correct for ngrok: the local ngrok agent connects FROM localhost.
# For production behind nginx/Caddy, set this to your proxy's IP instead.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"\n[REQUEST] {request.method} {request.url.path}")
    sys.stdout.flush()
    response = await call_next(request)
    return response


# ── Register routers ──────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(instagram_router)
app.include_router(instagram_auth_router)
app.include_router(flows_router)
app.include_router(templates_router)
app.include_router(broadcasts_router)
app.include_router(conversations_router)
app.include_router(analytics_router)
app.include_router(meta_webhook_router)   # GET/POST /webhook  (Meta-required top-level path)
app.include_router(webhook_router)        # GET/POST /api/webhook/* (existing)
app.include_router(test_router)


# ── Static routes ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "Dashboard not found"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    return {
        "instagram_app_id": os.getenv("INSTAGRAM_APP_ID", ""),
        "facebook_app_id": os.getenv("FACEBOOK_APP_ID", ""),
        "instagram_oauth_callback": "/auth/instagram/callback",
    }


@app.get("/api/debug/env")
async def debug_env():
    """
    Returns all configuration values with secrets masked.
    Use this to verify .env is loaded correctly.
    REMOVE this endpoint or add auth before going to production.
    """
    return get_safe_debug_config()


# ── Bootstrap ─────────────────────────────────────────────────────────────────
validate_env()
init_db()


@app.on_event("startup")
async def start_broadcast_worker():
    asyncio.create_task(run_worker())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=APP_PORT,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",  # matches ProxyHeadersMiddleware above
    )
