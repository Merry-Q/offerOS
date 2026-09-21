"""OfferOS FastAPI application entry."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.auth import seed_admin_user
from server.config import settings
from server.db import init_db
from server.demo import seed_demo_library
from server.routers import analytics, auth, dashboard, health, matches, preferences, resumes
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
app.include_router(preferences.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    settings.ensure_dirs()
    init_db()
    seed_admin_user()
    seed_sample_resume()
    seed_demo_library(reset=True)


def _html(name: str) -> FileResponse:
    return FileResponse(
        STATIC / name,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/healthz")
def healthz():
    """Unauthenticated liveness probe for nginx / load balancers."""
    return JSONResponse({"ok": True})


@app.get("/")
def index():
    return _html("index.html")


@app.get("/login")
def login_page():
    return RedirectResponse("/", status_code=302)


@app.get("/register")
def register_page():
    return RedirectResponse("/", status_code=302)


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
