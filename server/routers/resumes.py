from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from server.agents.resume_agent import analyze_resume
from server.auth import get_current_user
from server.config import settings
from server.db import dumps, get_db, loads, utc_now
from server.files import extract_text_from_file
from server.routers.analytics import track_event

router = APIRouter(tags=["resumes"])


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _serialize(row) -> dict[str, Any]:
    d = dict(row)
    d["profile"] = loads(d.pop("profile_json", None), None)
    d.pop("raw_text", None)
    d.pop("file_path", None)
    return d


@router.get("/resumes")
def list_resumes(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, file_name, file_type, status, profile_json, created_at, updated_at "
            "FROM resumes WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
    return {"items": [_serialize(r) for r in rows]}


@router.post("/resumes/upload")
async def upload_resume(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    suffix = Path(file.filename).suffix.lower().lstrip(".")
    if suffix not in ("pdf", "docx", "txt", "md"):
        raise HTTPException(400, "仅支持 pdf / docx / txt / md（.doc 请先转为 docx）")

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if not content:
        raise HTTPException(400, "空文件")
    if len(content) > max_bytes:
        raise HTTPException(400, f"文件过大，上限 {settings.max_upload_mb}MB")

    resume_id = "cv_" + uuid.uuid4().hex[:10]
    safe_name = f"{resume_id}.{suffix}"
    dest = settings.upload_dir / safe_name
    dest.write_bytes(content)

    display = Path(file.filename).stem
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO resumes (id, user_id, name, file_name, file_type, file_path, status, raw_text, profile_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (resume_id, user["id"], display, file.filename, suffix, str(dest), "uploaded", None, None, now, now),
        )
    track_event("resume_upload", {"resume_id": resume_id, "file_type": suffix}, user_id=user["id"])
    return parse_resume(resume_id, user)


@router.post("/resumes/{resume_id}/parse")
def parse_resume(resume_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "简历不存在")
        conn.execute(
            "UPDATE resumes SET status = ?, updated_at = ? WHERE id = ?",
            ("parsing", utc_now(), resume_id),
        )

    path = Path(row["file_path"])
    try:
        raw_text = extract_text_from_file(path, row["file_type"])
        profile, meta = analyze_resume(raw_text, row["file_name"])
        status = "parsed"
        track_event(
            "resume_parse_success",
            {"resume_id": resume_id, "llm_used": meta.get("used", False)},
            user_id=user["id"],
        )
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        track_event("resume_parse_fail", {"resume_id": resume_id, "error": str(exc)[:200]}, user_id=user["id"])
        with get_db() as conn:
            conn.execute(
                "UPDATE resumes SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), resume_id),
            )
        raise HTTPException(400, f"解析失败：{exc}") from exc

    now = utc_now()
    with get_db() as conn:
        conn.execute(
            "UPDATE resumes SET status = ?, raw_text = ?, profile_json = ?, updated_at = ? WHERE id = ?",
            (status, raw_text, dumps(profile), now, resume_id),
        )
        row = conn.execute(
            "SELECT id, name, file_name, file_type, status, profile_json, created_at, updated_at "
            "FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
    result = _serialize(row)
    result["llm"] = meta
    return result


@router.patch("/resumes/{resume_id}")
def rename_resume(resume_id: str, body: RenameBody, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE resumes SET name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (body.name.strip(), utc_now(), resume_id, user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "简历不存在")
        row = conn.execute(
            "SELECT id, name, file_name, file_type, status, profile_json, created_at, updated_at "
            "FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
    return _serialize(row)


@router.delete("/resumes/{resume_id}")
def delete_resume(resume_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        parsed = conn.execute(
            "SELECT COUNT(*) AS c FROM resumes WHERE status = 'parsed' AND user_id = ?",
            (user["id"],),
        ).fetchone()["c"]
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "简历不存在")
        if row["status"] == "parsed" and parsed <= 1:
            raise HTTPException(400, "至少保留一份已解析简历")
        path = row["file_path"]
        conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}
