"""OfferOS FastAPI application entry."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.auth import seed_admin_user
from server.config import settings
from server.db import init_db
from server.routers import analytics, auth, health, matches, resumes

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
app.include_router(analytics.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    settings.ensure_dirs()
    init_db()
    seed_admin_user()


@app.get("/api/healthz")
def healthz():
    """Unauthenticated liveness probe for nginx / load balancers."""
    return JSONResponse({"ok": True})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.get("/register")
def register_page():
    return FileResponse(STATIC / "register.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.get("/admin/login")
def admin_login_page():
    return FileResponse(STATIC / "admin-login.html")


@app.get("/admin/register")
def admin_register_page():
    return FileResponse(STATIC / "admin-register.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
