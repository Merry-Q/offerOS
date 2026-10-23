from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from server.auth import (
    create_session,
    delete_session,
    get_current_user,
    get_user_by_token,
    hash_password,
    verify_password,
)
from server.config import settings
from server.db import get_db, utc_now
from server.demo import issue_demo_session, demo_presets, SAMPLE_ANSWER, DEMO_USERNAME
from server.routers.analytics import track_event

router = APIRouter(tags=["auth"])


class AuthBody(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=6, max_length=72)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


class WorkspaceBody(BaseModel):
    clone_resume_id: str | None = None


def _public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def _token_from_headers(
    x_auth_token: str | None,
    authorization: str | None,
) -> str | None:
    if x_auth_token:
        return x_auth_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _admin_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin'"
    ).fetchone()["c"]


def _password_is_env_default(password_hash: str) -> bool:
    """True if hash still matches the ADMIN_PASSWORD from .env (incl. weak defaults)."""
    if not settings.admin_password:
        return False
    return verify_password(settings.admin_password, password_hash)


def _user_flags(row) -> dict:
    flags = {"must_change_password": False}
    if row["role"] == "admin" and _password_is_env_default(row["password_hash"]):
        flags["must_change_password"] = True
    return flags


@router.post("/auth/register")
def register(body: AuthBody):
    """Public user registration — always creates role=user."""
    username = body.username.strip()
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise HTTPException(400, "用户名已存在")

        user_id = "user_" + uuid.uuid4().hex[:10]
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, hash_password(body.password), "user", utc_now()),
        )
        row = conn.execute(
            "SELECT id, username, role, created_at, password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    token = create_session(user_id)
    track_event("auth_register", {"role": "user"}, user_id=user_id)
    return {"token": token, "user": _public_user(row), **_user_flags(row)}


@router.post("/auth/admin-bootstrap")
def admin_bootstrap_create(body: AuthBody):
    """Create the first admin only when none exists."""
    username = body.username.strip()
    with get_db() as conn:
        if _admin_count(conn) > 0:
            raise HTTPException(403, "已存在管理员，请直接登录")
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise HTTPException(400, "用户名已存在")
        user_id = "user_" + uuid.uuid4().hex[:10]
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, hash_password(body.password), "admin", utc_now()),
        )
        row = conn.execute(
            "SELECT id, username, role, created_at, password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    token = create_session(user_id)
    track_event("auth_register", {"role": "admin", "bootstrap": True}, user_id=user_id)
    return {"token": token, "user": _public_user(row), **_user_flags(row)}


@router.get("/auth/admin-bootstrap")
def admin_bootstrap_status():
    with get_db() as conn:
        count = _admin_count(conn)
    return {"admin_exists": count > 0, "can_register_admin": count == 0}


@router.post("/auth/demo")
def enter_demo(x_auth_token: str | None = Header(default=None, alias="X-Auth-Token")):
    """Public demo entry: no username/password. Shared fictional account."""
    existing = get_user_by_token(x_auth_token) if x_auth_token else None
    if existing and existing["username"].startswith("archive_"):
        return {"token": x_auth_token, "user": existing, "demo": False,
                "presets": demo_presets(), "sample_answer": SAMPLE_ANSWER}
    data = issue_demo_session()
    track_event("auth_demo", {"role": "user"}, user_id=data["user"]["id"])
    return data


@router.post("/auth/workspace")
def private_archive_workspace(body: WorkspaceBody | None = None, user: dict = Depends(get_current_user)):
    """Separate uploaded resumes from the shared fictional demo account."""
    if user["username"] != DEMO_USERNAME:
        return {"user": user}
    uid = "user_" + uuid.uuid4().hex
    now = utc_now()
    clone_id = None
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,'user',?)",
            (uid, "archive_" + uuid.uuid4().hex, hash_password(uuid.uuid4().hex), now),
        )
        # Only curated fictional demo resumes can be copied into a visitor workspace.
        if body and body.clone_resume_id and body.clone_resume_id.startswith("cv_demo_"):
            row = conn.execute("SELECT * FROM resumes WHERE id=? AND user_id=?", (body.clone_resume_id, user["id"])).fetchone()
            if row:
                values = dict(row)
                clone_id = "cv_demo_" + uuid.uuid4().hex
                values.update(id=clone_id, user_id=uid, created_at=now, updated_at=now)
                columns = list(values)
                conn.execute(f"INSERT INTO resumes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [values[c] for c in columns])
    visitor = {"id": uid, "username": "个人简历档案", "role": "user", "created_at": now}
    # Return the stored identity, so the next page load recognizes this workspace.
    with get_db() as conn:
        visitor["username"] = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()["username"]
    return {"token": create_session(uid), "user": visitor, "resume_id": clone_id}


@router.post("/auth/login")
def login(body: AuthBody):
    username = body.username.strip()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    token = create_session(row["id"])
    track_event("auth_login", {"role": row["role"]}, user_id=row["id"])
    return {"token": token, "user": _public_user(row), **_user_flags(row)}


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordBody,
    user: dict = Depends(get_current_user),
    x_auth_token: str | None = Header(default=None, alias="X-Auth-Token"),
    authorization: str | None = Header(default=None),
):
    if body.new_password.strip() == body.old_password:
        raise HTTPException(400, "新密码不能与旧密码相同")
    with get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        if not row or not verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(400, "旧密码不正确")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(body.new_password), user["id"]),
        )
        # Drop all other sessions; keep current if present
        current = _token_from_headers(x_auth_token, authorization)
        if current:
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token != ?",
                (user["id"], current),
            )
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    track_event("auth_change_password", {}, user_id=user["id"])
    return {"ok": True, "must_change_password": False}


@router.post("/auth/logout")
def logout(
    user: dict = Depends(get_current_user),
    x_auth_token: str | None = Header(default=None, alias="X-Auth-Token"),
    authorization: str | None = Header(default=None),
):
    token = _token_from_headers(x_auth_token, authorization)
    if token:
        delete_session(token)
    track_event("auth_logout", {}, user_id=user["id"])
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at, password_hash FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
    if not row:
        raise HTTPException(401, "登录已失效，请重新登录")
    return {"user": _public_user(row), **_user_flags(row)}
