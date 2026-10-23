"""OfferOS FastAPI application entry."""
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.auth import seed_admin_user
from server.config import settings
from server.db import init_db
from server.demo import seed_demo_library
from server.routers import analytics, auth, dashboard, health, matches, preferences, resumes
from server.routers import discovery
from server.sample_data import seed_sample_resume

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(
    title="OfferOS",
    version="2.0.0",
    docs_url=None if settings.disable_docs else "/docs",
    redoc_url=None if settings.disable_docs else "/redoc",
    openapi_url=None if settings.disable_docs else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=("*" not in settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(resumes.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(discovery.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    settings.ensure_dirs()
    init_db()
    discovery.recover_interrupted_runs()
    seed_admin_user()
    seed_sample_resume()
    seed_demo_library(reset=True)


def _public(path: str) -> str:
    base = settings.public_base_path
    if not path.startswith("/"):
        path = "/" + path
    if path == "/":
        return f"{base}/" if base else "/"
    return f"{base}{path}"


def _html(name: str) -> HTMLResponse:
    text = (STATIC / name).read_text(encoding="utf-8")
    base = settings.public_base_path
    inject = f"<script>window.OFFEROS_BASE={json.dumps(base)};</script>"
    if "</head>" in text:
        text = text.replace("</head>", inject + "</head>", 1)
    else:
        text = inject + text
    if base:
        text = text.replace('src="/static/', f'src="{base}/static/')
        text = text.replace("src='/static/", f"src='{base}/static/")
        text = text.replace('href="/static/', f'href="{base}/static/')
        text = text.replace('href="/admin', f'href="{base}/admin')
        text = text.replace('href="/login', f'href="{base}/login')
        text = text.replace('href="/register', f'href="{base}/register')
        text = text.replace('href="/"', f'href="{base}/"')
        text = text.replace("href='/'", f"href='{base}/'")
    return HTMLResponse(text, headers={"Cache-Control": "no-store"})


@app.get("/api/healthz")
def healthz():
    """Unauthenticated liveness probe for nginx / load balancers."""
    return JSONResponse({"ok": True})


@app.get("/")
def index():
    return _html("index.html")


@app.get("/login")
def login_page():
    return RedirectResponse(_public("/"), status_code=302)


@app.get("/register")
def register_page():
    return RedirectResponse(_public("/"), status_code=302)


@app.get("/admin")
def admin_page():
    return _html("admin.html")


@app.get("/admin/login")
def admin_login_page():
    return _html("admin-login.html")


@app.get("/admin/register")
def admin_register_page():
    return _html("admin-register.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
