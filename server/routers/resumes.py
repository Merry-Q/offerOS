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
from server.sample_data import SAMPLE_RESUME_ID, is_sample_resume
from server.resume_evidence import attach_resume_evidence

router = APIRouter(tags=["resumes"])

RESUME_SELECT = (
    "id, name, file_name, file_type, status, raw_text, profile_json, direction_tag, created_at, updated_at"
)


class PatchResumeBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    direction_tag: str | None = Field(None, max_length=80)


class AppendStoryBody(BaseModel):
    section: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    source_label: str | None = Field(None, max_length=120)


class ProfileBody(BaseModel):
    profile: dict[str, Any]


class InterviewReportBody(BaseModel):
    transcript: str = Field(min_length=10, max_length=50000)
    questions: list[dict[str, Any]] = Field(default_factory=list)


def _serialize(row, *, is_sample: bool = False) -> dict[str, Any]:
    d = dict(row)
    d["profile"] = loads(d.pop("profile_json", None), None)
    if d.get("raw_text") and d["profile"]:
        d["profile"] = attach_resume_evidence(d["profile"], d["raw_text"])
    d.pop("raw_text", None)
    d.pop("file_path", None)
    d["direction_tag"] = d.get("direction_tag") or ""
    d["is_sample"] = is_sample or is_sample_resume(d.get("id", ""))
    return d


@router.get("/resumes")
def list_resumes(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {RESUME_SELECT} FROM resumes WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
        sample = conn.execute(
            f"SELECT {RESUME_SELECT} FROM resumes WHERE id = ?",
            (SAMPLE_RESUME_ID,),
        ).fetchone()
    items = [_serialize(r) for r in rows]
    if sample:
        items.append(_serialize(sample, is_sample=True))
    return {"items": items, "max_upload_mb": settings.max_upload_mb}


@router.get("/resumes/{resume_id}/source")
def resume_source(resume_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, file_name, raw_text FROM resumes WHERE id=? AND (user_id=? OR id=?)",
            (resume_id, user["id"], SAMPLE_RESUME_ID),
        ).fetchone()
    if not row:
        raise HTTPException(404, "简历不存在")
    return {"id": row["id"], "file_name": row["file_name"], "raw_text": row["raw_text"] or ""}


@router.post("/resumes/upload")
async def upload_resume(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if user["username"] == "demo":
        raise HTTPException(409, "请先建立独立简历空间后上传")
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
    if is_sample_resume(resume_id):
        raise HTTPException(400, "示例简历不可重新解析")
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
        if not raw_text.strip():
            raise ValueError("文件没有可提取的文字，请上传包含文本的简历")
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
            f"SELECT {RESUME_SELECT} FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
    result = _serialize(row)
    result["llm"] = meta
    return result


@router.patch("/resumes/{resume_id}")
def patch_resume(resume_id: str, body: PatchResumeBody, user: dict = Depends(get_current_user)):
    if is_sample_resume(resume_id):
        raise HTTPException(400, "示例简历不可修改")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "没有可更新的字段")
    if "name" in fields and not (fields["name"] or "").strip():
        raise HTTPException(400, "名称不能为空")

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "简历不存在")

        sets: list[str] = []
        vals: list[Any] = []
        if "name" in fields:
            sets.append("name = ?")
            vals.append(fields["name"].strip())
        if "direction_tag" in fields:
            sets.append("direction_tag = ?")
            vals.append((fields["direction_tag"] or "").strip() or None)
        sets.append("updated_at = ?")
        vals.append(utc_now())
        vals.extend([resume_id, user["id"]])
        conn.execute(
            f"UPDATE resumes SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
            vals,
        )
        row = conn.execute(
            f"SELECT {RESUME_SELECT} FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
    track_event(
        "resume_patch",
        {"resume_id": resume_id, "fields": list(fields.keys())},
        user_id=user["id"],
    )
    return _serialize(row)


@router.put("/resumes/{resume_id}/profile")
def replace_profile(resume_id: str, body: ProfileBody, user: dict = Depends(get_current_user)):
    """Legacy endpoint: the uploaded file is now the only source of candidate facts."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM resumes WHERE id=? AND user_id=?", (resume_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "简历不存在")
    raise HTTPException(409, "简历档案仅依据上传文件，不支持补充简历外能力。请上传新版简历重新解析。")


@router.post("/resumes/{resume_id}/interview-report")
def interview_report(
    resume_id: str, body: InterviewReportBody, user: dict = Depends(get_current_user)
):
    with get_db() as conn:
        row = conn.execute(
            "SELECT profile_json, raw_text FROM resumes WHERE id = ? AND (user_id = ? OR id = ?)",
            (resume_id, user["id"], SAMPLE_RESUME_ID),
        ).fetchone()
    if not row:
        raise HTTPException(404, "简历不存在")
    fallback = {
        "overall": "回答已保存在本次页面中。为保护隐私，转写稿不发送给模型；请按结构提示自行复盘。",
        "scores": {},
        "strengths": ["能够围绕问题作答"],
        "improvements": ["用 STAR 结构补充背景、任务、行动和结果"],
        "next_practice": ["重新回答证据最弱的一题"],
    }
    return {"report": fallback, "llm": {"used": False, "local": True, "reason": "转写稿不出站"}}



@router.post("/resumes/{resume_id}/append-story")
def append_story(resume_id: str, body: AppendStoryBody, user: dict = Depends(get_current_user)):
    """Legacy endpoint retained to explain the current resume-only policy."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM resumes WHERE id=? AND user_id=?", (resume_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "简历不存在")
    raise HTTPException(409, "不支持追加简历外经历，请上传新版简历重新解析。")


@router.delete("/resumes/{resume_id}")
def delete_resume(resume_id: str, user: dict = Depends(get_current_user)):
    if is_sample_resume(resume_id):
        raise HTTPException(400, "示例简历不可删除")
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "简历不存在")
        path = row["file_path"]
        conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
    try:
        if path:
            Path(path).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}
