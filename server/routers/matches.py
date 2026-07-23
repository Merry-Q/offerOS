from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.agents.action_agent import build_action_report
from server.agents.jd_agent import analyze_jd
from server.agents.judge_agent import judge_match
from server.auth import get_current_user
from server.db import dumps, get_db, loads, utc_now
from server.routers.analytics import track_event

router = APIRouter(tags=["matches"])


class AnalyzeJdBody(BaseModel):
    jd_text: str = Field(min_length=20)
    job_id: str | None = None


class RunMatchBody(BaseModel):
    jd_text: str = Field(min_length=20)
    resume_id: str
    job_id: str | None = None
    jd_profile: dict | None = None


def _job_out(row, matches: list | None = None) -> dict[str, Any]:
    d = dict(row)
    d["jd_profile"] = loads(d.pop("jd_profile_json", None), None)
    if matches is not None:
        d["matches"] = matches
    return d


def _match_out(row) -> dict[str, Any]:
    d = dict(row)
    d["dims"] = loads(d.pop("dims_json"), [])
    d["strengths"] = loads(d.pop("strengths_json"), [])
    d["gaps"] = loads(d.pop("gaps_json"), [])
    d["jd_profile"] = loads(d.pop("jd_profile_json"), None)
    d["report"] = loads(d.pop("report_json"), None)
    d["llm_meta"] = loads(d.pop("llm_meta_json"), None)
    return d


@router.get("/jobs")
def list_jobs(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
        items = []
        for job in jobs:
            runs = conn.execute(
                "SELECT * FROM match_runs WHERE job_id = ? ORDER BY version DESC",
                (job["id"],),
            ).fetchall()
            items.append(_job_out(job, [_match_out(r) for r in runs]))
    return {"items": items}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user["id"]),
        ).fetchone()
        if not job:
            raise HTTPException(404, "岗位不存在")
        runs = conn.execute(
            "SELECT * FROM match_runs WHERE job_id = ? ORDER BY version DESC",
            (job_id,),
        ).fetchall()
    return _job_out(job, [_match_out(r) for r in runs])


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "岗位不存在")
    track_event("job_delete", {"job_id": job_id}, user_id=user["id"])
    return {"ok": True}


@router.post("/match/analyze-jd")
def analyze_jd_api(body: AnalyzeJdBody, user: dict = Depends(get_current_user)):
    t0 = time.time()
    profile, meta = analyze_jd(body.jd_text)
    track_event(
        "jd_analyze_done",
        {
            "success": True,
            "duration_ms": int((time.time() - t0) * 1000),
            "llm_used": meta.get("used", False),
        },
        user_id=user["id"],
    )
    return {"jd_profile": profile, "llm": meta}


@router.post("/match/run")
def run_match(body: RunMatchBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    track_event(
        "match_start",
        {"resume_id": body.resume_id, "rematch": bool(body.job_id)},
        user_id=uid,
    )
    t0 = time.time()

    with get_db() as conn:
        resume = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
            (body.resume_id, uid),
        ).fetchone()
        if not resume or resume["status"] != "parsed":
            raise HTTPException(400, "请选择已解析的简历")
        resume_profile = loads(resume["profile_json"], {})

    jd_profile, jd_meta = (
        (body.jd_profile, {"used": False, "reason": "复用上一步 JD 档案"})
        if body.jd_profile
        else analyze_jd(body.jd_text)
    )
    if not body.jd_profile:
        track_event("jd_analyze_done", {"success": True, "llm_used": jd_meta.get("used", False)}, user_id=uid)

    judge, judge_meta = judge_match(jd_profile, resume_profile)
    track_event(
        "judge_done",
        {"score": judge["score"], "level": judge["level"], "llm_used": judge_meta.get("used", False)},
        user_id=uid,
    )

    report, action_meta = build_action_report(judge, resume_profile, jd_profile)
    now = utc_now()
    title = jd_profile.get("title") or "未命名岗位"
    llm_meta = {"jd": jd_meta, "judge": judge_meta, "action": action_meta}
    mode_used = any(m.get("used") for m in (jd_meta, judge_meta, action_meta))
    track_event("llm_mode", {"llm_used": mode_used}, user_id=uid)

    with get_db() as conn:
        if body.job_id:
            job = conn.execute(
                "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
                (body.job_id, uid),
            ).fetchone()
            if not job:
                raise HTTPException(404, "岗位不存在")
            job_id = body.job_id
            version = (
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS v FROM match_runs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()["v"]
                + 1
            )
            conn.execute(
                "UPDATE jobs SET title = ?, jd_text = ?, jd_profile_json = ?, updated_at = ? WHERE id = ?",
                (title, body.jd_text, dumps(jd_profile), now, job_id),
            )
            track_event("rematch", {"job_id": job_id, "version": version}, user_id=uid)
        else:
            job_id = "job_" + uuid.uuid4().hex[:10]
            version = 1
            conn.execute(
                "INSERT INTO jobs (id, user_id, title, jd_text, jd_profile_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, uid, title, body.jd_text, dumps(jd_profile), now, now),
            )

        match_id = "m_" + uuid.uuid4().hex[:10]
        conn.execute(
            """
            INSERT INTO match_runs (
              id, job_id, version, resume_id, resume_name, pref_id, pref_name,
              score, level, one_liner, dims_json, threshold, raw_score,
              strengths_json, gaps_json, jd_profile_json, report_json, llm_meta_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id, job_id, version, body.resume_id, resume["name"], "", "",
                judge["score"], judge["level"], judge["one_liner"], dumps(judge["dims"]),
                judge["threshold"], judge["raw"], dumps(judge["strengths"]), dumps(judge["gaps"]),
                dumps(jd_profile), dumps(report), dumps(llm_meta), now,
            ),
        )

    track_event(
        "report_generated",
        {
            "job_id": job_id,
            "match_id": match_id,
            "version": version,
            "score": judge["score"],
            "level": judge["level"],
            "duration_ms": int((time.time() - t0) * 1000),
        },
        user_id=uid,
    )

    return {
        "job_id": job_id,
        "match_id": match_id,
        "version": version,
        "title": title,
        "jd_profile": jd_profile,
        "judge": judge,
        "report": report,
        "resume_name": resume["name"],
        "llm": llm_meta,
    }
