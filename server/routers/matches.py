from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from server.agents.action_agent import build_action_report
from server.agents.jd_agent import analyze_jd, job_tags_from_profile
from server.agents.judge_agent import judge_match
from server.agents.research_agent import research_company, clean_cached_research
from server.agents.url_jd_agent import extract_jd_from_url
from server.auth import get_current_user
from server.cache_store import (
    cache_delete,
    cache_get,
    cache_set,
    jd_cache_key,
    judge_cache_key,
    report_cache_key,
    text_hash,
)
from server.config import settings
from server.db import dumps, get_db, loads, utc_now
from server.routers.analytics import track_event
from server.sample_data import SAMPLE_RESUME_ID
from server.resume_evidence import attach_resume_evidence
from server.interview_preparation import enrich_interview_preparation

router = APIRouter(tags=["matches"])


APPLY_STATUSES = ("待决策", "待改简历", "待投", "已投", "面试中", "结束")
ApplyStatus = Literal["待决策", "待改简历", "待投", "已投", "面试中", "结束"]


class AnalyzeJdBody(BaseModel):
    jd_text: str = Field(min_length=20)
    job_id: str | None = None


class ResearchBody(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    title: str | None = Field(None, max_length=120)
    industry: str | None = Field(None, max_length=120)
    match_id: str | None = None


class SplitJdBody(BaseModel):
    text: str = Field(min_length=20, max_length=100000)


class RunMatchBody(BaseModel):
    jd_text: str = Field(min_length=20)
    resume_id: str
    job_id: str | None = None
    jd_profile: dict | None = None
    company: str | None = None
    location: str | None = None
    source_url: str | None = None
    employment_type: str | None = None
    auto_report: bool = True
    batch_id: str | None = None
    starred: bool | None = None


class ExtractJdUrlBody(BaseModel):
    url: str = Field(min_length=4)


class RecommendResumeBody(BaseModel):
    jd_text: str = Field(min_length=20)
    jd_profile: dict | None = None


class BatchItemBody(BaseModel):
    jd_text: str = Field(min_length=20)
    title: str | None = None
    company: str | None = None
    location: str | None = None
    source_url: str | None = None
    employment_type: str | None = None


class BatchMatchBody(BaseModel):
    items: list[BatchItemBody] = Field(min_length=1, max_length=20)
    resume_id: str | None = None
    auto_pick_resume: bool = True
    auto_report: bool = False
    request_key: str | None = Field(default=None, max_length=80)


class StarBody(BaseModel):
    starred: bool


class PatchJobBody(BaseModel):
    company: str | None = None
    location: str | None = None
    source_url: str | None = None
    employment_type: str | None = None
    apply_status: ApplyStatus | None = None
    closed_reason: str | None = None
    title: str | None = None
    starred: bool | None = None


class BulkJobStatusBody(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)
    apply_status: ApplyStatus


class CreateDraftBody(BaseModel):
    match_id: str
    source_text: str = ""
    suggested_text: str = Field(min_length=1)
    edited_text: str | None = None
    source_label: str | None = None


class PatchDraftBody(BaseModel):
    edited_text: str = Field(min_length=1)


class ActionItemBody(BaseModel):
    item_key: str = Field(min_length=1, max_length=80)
    completed: bool


def _job_out(row, matches: list | None = None) -> dict[str, Any]:
    d = dict(row)
    d["jd_profile"] = loads(d.pop("jd_profile_json", None), None)
    d["company"] = d.get("company") or ""
    d["location"] = d.get("location") or ""
    d["source_url"] = d.get("source_url") or ""
    d["employment_type"] = d.get("employment_type") or ""
    d["apply_status"] = d.get("apply_status") or "待决策"
    d["starred"] = bool(d.get("starred") or 0)
    d["batch_id"] = d.get("batch_id") or None
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
    d["report_modules"] = loads(d.pop("report_modules_json", None), None)
    d["starred"] = bool(d.get("starred") or 0)
    d["batch_id"] = d.get("batch_id") or None
    d["auto_report"] = bool(d.get("auto_report") if d.get("auto_report") is not None else 1)
    # 兼容旧行缺省状态
    if not d.get("judge_status"):
        d["judge_status"] = "done" if d.get("score") is not None else "idle"
    if not d.get("report_status"):
        d["report_status"] = "done" if d.get("report") else ("pending" if d.get("score") is not None else "idle")
    judge_payload = _judge_payload(d)
    d["recommended_action"] = _recommended_action(judge_payload)
    d["action_summary"] = _action_summary(d.get("report"), judge_payload)
    return d


def _judge_payload(row_or_judge: dict[str, Any]) -> dict[str, Any]:
    """从 match_run 行或 judge dict 组装前端 judge 结构。"""
    if "dims" in row_or_judge and isinstance(row_or_judge.get("dims"), list):
        gaps = row_or_judge.get("gaps") or []
        return {
            "score": row_or_judge.get("score"),
            "level": row_or_judge.get("level"),
            "one_liner": row_or_judge.get("one_liner"),
            "dims": row_or_judge.get("dims") or [],
            "threshold": row_or_judge.get("threshold"),
            "raw": row_or_judge.get("raw_score", row_or_judge.get("raw")),
            "strengths": row_or_judge.get("strengths") or [],
            "gaps": gaps,
            "hard_gate_warnings": [g for g in gaps if isinstance(g, dict) and g.get("hard_gate")],
        }
    return row_or_judge


def _recommended_action(judge: dict[str, Any] | None, *, complete: bool = True) -> dict[str, Any]:
    if not complete:
        return {"value": "补全信息", "fatal_warning": False}
    if not judge:
        return {"value": "重试", "fatal_warning": False}
    level = judge.get("level") or ""
    gaps = judge.get("gaps") or []
    fatal = any(isinstance(g, dict) and g.get("severity") == "fatal" for g in gaps)
    if level == "不建议投":
        value = "不建议投"
    elif level == "冲":
        value = "修改后投"
    else:
        value = "去投递"
    return {"value": value, "fatal_warning": fatal}


def _action_summary(report: dict[str, Any] | None, judge: dict[str, Any]) -> dict[str, Any] | None:
    if not report:
        return None
    gaps = report.get("gaps_detail") or judge.get("gaps") or []
    rewrites = report.get("resume_rewrite") or []
    interviews = report.get("interview") or []
    must_do = []
    for idx, item in enumerate((rewrites or [])[:3]):
        if not isinstance(item, dict):
            continue
        must_do.append(
            {
                "key": f"rewrite_{idx}",
                "title": item.get("section") or item.get("action") or f"修改项 {idx + 1}",
                "text": item.get("after") or item.get("rewrite") or item.get("suggestion") or "",
                "source_text": item.get("before") or item.get("original") or "",
                "source_resume": item.get("source_resume") or "",
            }
        )
    evidence = []
    for item in gaps[:3]:
        if isinstance(item, dict):
            evidence.append(item.get("fix_plan") or item.get("text") or "")
        else:
            evidence.append(str(item))
    questions = []
    for item in interviews[:3]:
        if isinstance(item, dict):
            questions.append(item.get("question") or item.get("q") or "")
        else:
            questions.append(str(item))
    return {
        "decision": {
            "level": judge.get("level"),
            "score": judge.get("score"),
            "conclusion": report.get("conclusion") or judge.get("one_liner") or "",
        },
        "must_do_items": must_do,
        "evidence_suggestions": [x for x in evidence if x],
        "interview_focus": [x for x in questions if x],
        "next_action": _recommended_action(judge),
    }


def _resolve_jd_profile(jd_text: str, provided: dict | None) -> tuple[dict[str, Any], dict]:
    if provided:
        return provided, {"used": False, "cached": False, "reason": "复用上一步 JD 档案"}
    key = jd_cache_key("jd-parse-v3:" + jd_text)
    hit = cache_get(key)
    if isinstance(hit, dict) and hit.get("title"):
        return hit, {"used": False, "cached": True, "reason": "JD 档案缓存命中"}
    profile, meta = analyze_jd(jd_text)
    if meta.get("used"):
        cache_set(key, "jd_profile", profile)
    meta = {**meta, "cached": False}
    return profile, meta


def _resolve_judge(
    resume_id: str,
    jd_text: str,
    jd_profile: dict,
    resume_profile: dict,
) -> tuple[dict[str, Any], dict]:
    evidence_key = "privacy-v1:" + resume_id + ":" + text_hash(dumps(resume_profile.get("resume_sections") or {})) + ":" + text_hash(dumps(jd_profile))
    key = judge_cache_key(evidence_key, jd_text)
    hit = cache_get(key)
    if isinstance(hit, dict) and hit.get("score") is not None and hit.get("level"):
        return hit, {"used": False, "cached": True, "reason": "判分缓存命中"}
    judge, meta = judge_match(jd_profile, resume_profile)
    cache_set(key, "judge", judge)
    return judge, {**meta, "cached": False}


def _set_report_status(
    match_id: str,
    status: str,
    *,
    report: dict | None = None,
    llm_meta: dict | None = None,
    error: str | None = None,
    report_duration_ms: int | None = None,
    report_modules: dict | None = None,
) -> None:
    now = utc_now()
    with get_db() as conn:
        row = conn.execute("SELECT llm_meta_json FROM match_runs WHERE id = ?", (match_id,)).fetchone()
        if not row:
            return
        conn.execute(
            """
            UPDATE match_runs SET
              report_status = ?,
              report_error = ?,
              report_updated_at = ?,
              report_json = COALESCE(?, report_json),
              llm_meta_json = json_patch(COALESCE(llm_meta_json, '{}'), ?),
              report_duration_ms = COALESCE(?, report_duration_ms),
              report_modules_json = COALESCE(?, report_modules_json)
            WHERE id = ?
            """,
            (
                status,
                error,
                now,
                dumps(report) if report is not None else None,
                dumps(llm_meta or {}),
                report_duration_ms,
                dumps(report_modules) if report_modules is not None else None,
                match_id,
            ),
        )


def _generate_report_job(
    match_id: str,
    user_id: str,
    judge: dict[str, Any],
    resume_profile: dict[str, Any],
    jd_profile: dict[str, Any],
    jd_text: str,
    resume_id: str,
    *,
    bust_cache: bool = False,
) -> None:
    """后台线程：模块化生成 Action 报告，并增量落库。"""
    evidence_key = "privacy-v1:" + resume_id + ":" + text_hash(dumps(resume_profile.get("resume_sections") or {}))
    rkey = report_cache_key("interview-preparation-v4:" + evidence_key + ":" + text_hash(dumps(jd_profile)), jd_text)
    if bust_cache:
        cache_delete(rkey)
    else:
        cached = cache_get(rkey)
        if isinstance(cached, dict) and cached.get("match_table"):
            mods = {"m1": "done", "m2": "done", "m3": "done", "m4": "done"}
            _set_report_status(
                match_id,
                "done",
                report=cached,
                llm_meta={"action": {"used": False, "cached": True, "modular": True, "content_version": 4}},
                error=None,
                report_duration_ms=0,
                report_modules=mods,
            )
            track_event(
                "report_generated",
                {
                    "match_id": match_id,
                    "score": judge.get("score"),
                    "level": judge.get("level"),
                    "duration_ms": 0,
                    "report_duration_ms": 0,
                    "async": True,
                    "cached": True,
                },
                user_id=user_id,
            )
            return

    _set_report_status(
        match_id,
        "running",
        error=None,
        report_modules={"m1": "pending", "m2": "pending", "m3": "pending", "m4": "pending"},
    )
    t0 = time.time()

    def on_progress(modules: dict[str, str], partial: dict | None) -> None:
        # 增量写入：running 期间也更新 report_json，便于前端逐步渲染
        _set_report_status(
            match_id,
            "running",
            report=partial,
            report_modules=modules,
            error=None,
        )

    try:
        report, action_meta = build_action_report(
            judge,
            resume_profile,
            jd_profile,
            on_progress=on_progress,
        )
        duration_ms = int((time.time() - t0) * 1000)
        action_meta["content_version"] = 4
        cache_set(rkey, "report", report)
        _set_report_status(
            match_id,
            "done",
            report=report,
            llm_meta={"action": action_meta},
            error=None,
            report_duration_ms=duration_ms,
            report_modules={"m1": "done", "m2": "done", "m3": "done", "m4": "done"},
        )
        track_event(
            "report_generated",
            {
                "match_id": match_id,
                "score": judge.get("score"),
                "level": judge.get("level"),
                "duration_ms": duration_ms,
                "report_duration_ms": duration_ms,
                "async": True,
                "modular": True,
                "cached": False,
                "cross_resume": False,
            },
            user_id=user_id,
        )
        track_event(
            "llm_mode",
            {"llm_used": bool(action_meta.get("used")), "stage": "action", "modular": True},
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.time() - t0) * 1000)
        _set_report_status(
            match_id,
            "failed",
            error=str(exc)[:300],
            report_duration_ms=duration_ms,
        )
        track_event(
            "report_fail",
            {
                "match_id": match_id,
                "duration_ms": duration_ms,
                "error": str(exc)[:200],
            },
            user_id=user_id,
        )


def _owned_match(conn, match_id: str, user_id: str):
    return conn.execute(
        """
        SELECT mr.*, j.user_id AS job_user_id, j.title AS job_title, j.company AS job_company, j.jd_text AS job_jd_text
        FROM match_runs mr
        JOIN jobs j ON j.id = mr.job_id
        WHERE mr.id = ? AND j.user_id = ?
        """,
        (match_id, user_id),
    ).fetchone()


def _enqueue_report_job(
    match_id: str,
    user_id: str,
    judge: dict[str, Any],
    resume_profile: dict[str, Any],
    jd_profile: dict[str, Any],
    jd_text: str,
    resume_id: str,
    *,
    bust_cache: bool = False,
) -> None:
    """后台线程生成报告，避免长时间 LLM 占用请求 worker。"""
    t = threading.Thread(
        target=_generate_report_job,
        args=(match_id, user_id, judge, resume_profile, jd_profile, jd_text, resume_id),
        kwargs={"bust_cache": bust_cache},
        daemon=True,
        name=f"report-{match_id}",
    )
    t.start()


def _persist_match(
    *,
    uid: str,
    jd_text: str,
    jd_profile: dict[str, Any],
    resume_id: str,
    resume_name: str,
    judge: dict[str, Any],
    llm_meta: dict[str, Any],
    judge_duration_ms: int,
    job_id: str | None = None,
    company: str | None = None,
    location: str | None = None,
    source_url: str | None = None,
    employment_type: str | None = None,
    batch_id: str | None = None,
    starred: bool | None = None,
    auto_report: bool = True,
    title_override: str | None = None,
) -> dict[str, Any]:
    """落库 job + match_run。返回 job_id/match_id/version/title/report_status 等。"""
    now = utc_now()
    tags = job_tags_from_profile(jd_profile, jd_text)
    title = (title_override or "").strip() or tags["title"]
    jd_hash = text_hash(jd_text)
    # 用户改正优先，否则用 JD 自动标签
    company_v = (company or "").strip() or tags["company"] or None
    location_v = (location or "").strip() or tags["location"] or None
    emp_v = (employment_type or "").strip() or tags["employment_type"] or None
    source_url_v = (source_url or "").strip() or None
    starred_v = 1 if starred else 0
    jd_profile = {
        **jd_profile,
        "title": title,
        "company": company_v or "",
        "location": location_v or "",
        "employment_type": emp_v or tags["employment_type"],
        "level": tags["level"] or jd_profile.get("level") or "未知",
    }
    report_status = "pending" if auto_report else "idle"
    report_modules = (
        dumps({"m1": "pending", "m2": "pending", "m3": "pending", "m4": "pending"})
        if auto_report
        else None
    )
    is_rematch = bool(job_id)

    with get_db() as conn:
        if job_id:
            job = conn.execute(
                "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
                (job_id, uid),
            ).fetchone()
            if not job:
                raise HTTPException(404, "岗位不存在")
            version = (
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS v FROM match_runs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()["v"]
                + 1
            )
            conn.execute(
                """
                UPDATE jobs SET
                  title = ?, jd_text = ?, jd_profile_json = ?, updated_at = ?,
                  company = COALESCE(?, company),
                  location = COALESCE(?, location),
                  source_url = COALESCE(?, source_url),
                  employment_type = COALESCE(?, employment_type),
                  batch_id = COALESCE(?, batch_id)
                WHERE id = ?
                """,
                (
                    title,
                    jd_text,
                    dumps(jd_profile),
                    now,
                    company_v,
                    location_v,
                    source_url_v,
                    emp_v,
                    batch_id,
                    job_id,
                ),
            )
        else:
            job_id = "job_" + uuid.uuid4().hex[:10]
            version = 1
            conn.execute(
                """
                INSERT INTO jobs (
                  id, user_id, title, jd_text, jd_profile_json,
                  company, location, source_url, employment_type,
                  batch_id, apply_status, starred,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    uid,
                    title,
                    jd_text,
                    dumps(jd_profile),
                    company_v,
                    location_v,
                    source_url_v,
                    emp_v,
                    batch_id,
                    "待决策",
                    starred_v,
                    now,
                    now,
                ),
            )

        match_id = "m_" + uuid.uuid4().hex[:10]
        conn.execute(
            """
            INSERT INTO match_runs (
              id, job_id, version, resume_id, resume_name, pref_id, pref_name,
              score, level, one_liner, dims_json, threshold, raw_score,
              strengths_json, gaps_json, jd_profile_json, report_json, llm_meta_json,
              judge_status, report_status, report_error, report_updated_at,
              judge_duration_ms, report_duration_ms, report_modules_json, jd_text_hash,
              starred, batch_id, auto_report, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                job_id,
                version,
                resume_id,
                resume_name,
                "",
                "",
                judge["score"],
                judge["level"],
                judge["one_liner"],
                dumps(judge["dims"]),
                judge["threshold"],
                judge["raw"],
                dumps(judge["strengths"]),
                dumps(judge["gaps"]),
                dumps(jd_profile),
                None,
                dumps(llm_meta),
                "done",
                report_status,
                None,
                now,
                judge_duration_ms,
                None,
                report_modules,
                jd_hash,
                starred_v,
                batch_id,
                1 if auto_report else 0,
                now,
            ),
        )

    return {
        "job_id": job_id,
        "match_id": match_id,
        "version": version,
        "title": title,
        "report_status": report_status,
        "is_rematch": is_rematch,
        "auto_report": auto_report,
    }


def _run_match_core(
    *,
    uid: str,
    jd_text: str,
    resume_id: str,
    resume_row: Any,
    resume_profile: dict[str, Any],
    jd_profile_provided: dict | None = None,
    job_id: str | None = None,
    company: str | None = None,
    location: str | None = None,
    source_url: str | None = None,
    employment_type: str | None = None,
    batch_id: str | None = None,
    starred: bool | None = None,
    auto_report: bool = True,
    title_override: str | None = None,
    track_start: bool = True,
) -> dict[str, Any]:
    """解析 JD → 判分 → 落库 → 按需入队报告。"""
    if track_start:
        track_event(
            "match_start",
            {"resume_id": resume_id, "rematch": bool(job_id), "batch_id": batch_id},
            user_id=uid,
        )
    t0 = time.time()

    jd_profile, jd_meta = _resolve_jd_profile(jd_text, jd_profile_provided)
    if not jd_profile_provided:
        track_event(
            "jd_analyze_done",
            {
                "success": True,
                "llm_used": jd_meta.get("used", False),
                "cached": bool(jd_meta.get("cached")),
            },
            user_id=uid,
        )

    if title_override:
        jd_profile = {**jd_profile, "title": title_override}

    t_judge = time.time()
    judge, judge_meta = _resolve_judge(resume_id, jd_text, jd_profile, resume_profile)
    judge_duration_ms = int((time.time() - t_judge) * 1000)
    time_to_decision_ms = int((time.time() - t0) * 1000)
    track_event(
        "judge_done",
        {
            "score": judge["score"],
            "level": judge["level"],
            "llm_used": judge_meta.get("used", False),
            "cached": bool(judge_meta.get("cached")),
            "judge_duration_ms": judge_duration_ms,
            "time_to_decision_ms": time_to_decision_ms,
            "duration_ms": time_to_decision_ms,
            "batch_id": batch_id,
        },
        user_id=uid,
    )

    llm_meta = {"jd": jd_meta, "judge": judge_meta, "privacy_version": 1, "jd_parse_version": 3,
                "resume_evidence_hash": text_hash(dumps(resume_profile.get("resume_sections") or {}))}
    mode_used = any(m.get("used") for m in (jd_meta, judge_meta))
    track_event(
        "llm_mode",
        {
            "llm_used": mode_used,
            "stage": "judge",
            "cached_any": bool(jd_meta.get("cached") or judge_meta.get("cached")),
        },
        user_id=uid,
    )

    resume_name = resume_row["name"]
    persisted = _persist_match(
        uid=uid,
        jd_text=jd_text,
        jd_profile=jd_profile,
        resume_id=resume_id,
        resume_name=resume_name,
        judge=judge,
        llm_meta=llm_meta,
        judge_duration_ms=judge_duration_ms,
        job_id=job_id,
        company=company,
        location=location,
        source_url=source_url,
        employment_type=employment_type,
        batch_id=batch_id,
        starred=starred,
        auto_report=auto_report,
        title_override=title_override,
    )

    if persisted["is_rematch"]:
        track_event(
            "rematch",
            {"job_id": persisted["job_id"], "version": persisted["version"]},
            user_id=uid,
        )
    track_event(
        "match_judge_saved",
        {
            "job_id": persisted["job_id"],
            "match_id": persisted["match_id"],
            "version": persisted["version"],
            "score": judge["score"],
            "level": judge["level"],
            "judge_duration_ms": judge_duration_ms,
            "time_to_decision_ms": time_to_decision_ms,
            "report_status": persisted["report_status"],
            "judge_cached": bool(judge_meta.get("cached")),
            "batch_id": batch_id,
        },
        user_id=uid,
    )

    if auto_report:
        _enqueue_report_job(
            persisted["match_id"],
            uid,
            judge,
            resume_profile,
            jd_profile,
            jd_text,
            resume_id,
        )

    report_modules = (
        {"m1": "pending", "m2": "pending", "m3": "pending", "m4": "pending"}
        if auto_report
        else None
    )
    return {
        "job_id": persisted["job_id"],
        "match_id": persisted["match_id"],
        "version": persisted["version"],
        "title": persisted["title"],
        "jd_profile": jd_profile,
        "judge": judge,
        "report": None,
        "resume_name": resume_name,
        "resume_id": resume_id,
        "llm": llm_meta,
        "judge_status": "done",
        "report_status": persisted["report_status"],
        "report_modules": report_modules,
        "judge_duration_ms": judge_duration_ms,
        "time_to_decision_ms": time_to_decision_ms,
        "company": (company or "").strip() or jd_profile.get("company") or "",
        "location": (location or "").strip() or jd_profile.get("location") or "",
        "employment_type": (employment_type or "").strip()
        or jd_profile.get("employment_type")
        or "",
        "source_url": (source_url or "").strip() or "",
        "batch_id": batch_id,
        "cached": {
            "jd": bool(jd_meta.get("cached")),
            "judge": bool(judge_meta.get("cached")),
        },
        "recommended_action": _recommended_action(judge),
    }


def _fetch_resume(conn, resume_id: str, uid: str):
    row = conn.execute(
        "SELECT * FROM resumes WHERE id = ? AND (user_id = ? OR id = ?)",
        (resume_id, uid, SAMPLE_RESUME_ID),
    ).fetchone()
    return _resume_with_evidence(row) if row else None


def _resume_with_evidence(row) -> dict:
    item = dict(row)
    profile = loads(item.get("profile_json"), {}) or {}
    if item.get("raw_text"):
        profile = attach_resume_evidence(profile, item["raw_text"])
    item["profile_json"] = dumps(profile)
    return item


def _list_parsed_resumes(uid: str) -> list[Any]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM resumes WHERE user_id = ? AND status = ? ORDER BY updated_at DESC",
            (uid, "parsed"),
        ).fetchall()
        sample = conn.execute(
            "SELECT * FROM resumes WHERE id = ? AND status = ?",
            (SAMPLE_RESUME_ID, "parsed"),
        ).fetchone()
    items = list(rows)
    if sample:
        items.append(sample)
    return [_resume_with_evidence(row) for row in items]


def _tokens(text: str) -> set[str]:
    parts = re.split(r"[\s,，、;/|｜+（）()【】\[\]{}]+", (text or "").lower())
    return {p for p in parts if len(p) >= 2}


def _overlap_score(jd_profile: dict, resume_profile: dict) -> tuple[float, str]:
    """轻量文本重叠分（0-100）+ 简短理由。"""
    jd_bits: list[str] = []
    for key in ("must_haves", "core_requirements", "nice_to_haves"):
        for x in jd_profile.get(key) or []:
            jd_bits.append(str(x))
    jd_bits.append(str(jd_profile.get("summary") or ""))
    jd_bits.append(str(jd_profile.get("title") or ""))
    jd_tok = _tokens(" ".join(jd_bits))

    resume_bits: list[str] = []
    for key in ("skills", "strengths", "evidence"):
        for x in resume_profile.get(key) or []:
            resume_bits.append(str(x))
    resume_bits.append(str(resume_profile.get("summary") or ""))
    resume_tok = _tokens(" ".join(resume_bits))

    if not jd_tok:
        return 40.0, "JD 关键词较少，仅作粗估"
    hit = jd_tok & resume_tok
    ratio = len(hit) / max(len(jd_tok), 1)
    score = round(min(95.0, 25 + ratio * 90), 1)
    if hit:
        sample = "、".join(sorted(hit)[:4])
        reason = f"关键词重叠约 {int(ratio * 100)}%（如 {sample}）"
    else:
        reason = "关键词重叠较低，建议换方向或补证据"
    return score, reason


def _recommend_one(
    resume_row: Any,
    jd_text: str,
    jd_profile: dict,
    *,
    use_judge: bool,
) -> dict[str, Any]:
    profile = loads(resume_row["profile_json"], {}) or {}
    if use_judge:
        judge, _meta = _resolve_judge(resume_row["id"], jd_text, jd_profile, profile)
        return {
            "resume_id": resume_row["id"],
            "name": resume_row["name"],
            "score_estimate": judge.get("score"),
            "reason": judge.get("one_liner") or "判分结果",
            "direction_tag": resume_row["direction_tag"] if "direction_tag" in resume_row.keys() else None,
            "level": judge.get("level"),
            "evidence_refs": (judge.get("strengths") or [])[:3],
            "key_gaps": [
                x.get("text") for x in (judge.get("gaps") or [])[:2] if isinstance(x, dict)
            ],
        }
    score, reason = _overlap_score(jd_profile, profile)
    return {
        "resume_id": resume_row["id"],
        "name": resume_row["name"],
        "score_estimate": int(round(score)),
        "reason": reason,
        "direction_tag": resume_row["direction_tag"] if "direction_tag" in resume_row.keys() else None,
    }


@router.get("/jobs")
def list_jobs(
    user: dict = Depends(get_current_user),
    company: str | None = Query(None),
    title: str | None = Query(None, description="岗位标题精确或包含"),
    location: str | None = Query(None),
    employment_type: str | None = Query(None),
    apply_status: str | None = Query(None),
    q: str | None = Query(None, description="自由文本搜索"),
):
    with get_db() as conn:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
        items = []
        for job in jobs:
            # 精确标签筛选（匹配库下拉）；兼容旧数据用 contains
            if company and (job["company"] or "").strip() != company.strip():
                if company.lower() not in (job["company"] or "").lower():
                    continue
            if title and (job["title"] or "").strip() != title.strip():
                if title.lower() not in (job["title"] or "").lower():
                    continue
            if location and (job["location"] or "").strip() != location.strip():
                if location.lower() not in (job["location"] or "").lower():
                    continue
            emp = (job["employment_type"] if "employment_type" in job.keys() else None) or ""
            if employment_type and emp.strip() != employment_type.strip():
                continue
            status = job["apply_status"] or "待决策"
            if apply_status and apply_status != status:
                continue
            if q:
                blob = " ".join(
                    [
                        job["title"] or "",
                        job["company"] or "",
                        job["location"] or "",
                        emp,
                        job["jd_text"] or "",
                        job["source_url"] or "",
                    ]
                ).lower()
                if q.lower() not in blob:
                    continue
            runs = conn.execute(
                "SELECT * FROM match_runs WHERE job_id = ? ORDER BY version DESC",
                (job["id"],),
            ).fetchall()
            items.append(_job_out(job, [_match_out(r) for r in runs]))
    return {"items": items}


@router.get("/jobs/facets")
def job_facets(user: dict = Depends(get_current_user)):
    """匹配库筛选项：来自用户岗位库已有标签（非手填）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT title, company, location, employment_type FROM jobs WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
    companies: set[str] = set()
    titles: set[str] = set()
    locations: set[str] = set()
    employment_types: set[str] = set()
    for r in rows:
        c = (r["company"] or "").strip()
        t = (r["title"] or "").strip()
        loc = (r["location"] or "").strip()
        emp = (r["employment_type"] or "").strip() if "employment_type" in r.keys() else ""
        if c:
            companies.add(c)
        if t:
            titles.add(t)
        if loc:
            locations.add(loc)
        if emp:
            employment_types.add(emp)
    return {
        "companies": sorted(companies),
        "titles": sorted(titles),
        "locations": sorted(locations),
        "employment_types": sorted(employment_types),
    }


@router.get("/jobs/companies/summary")
def companies_summary(user: dict = Depends(get_current_user)):
    """按公司名聚合：岗位数、最新分均值、档位分布。"""
    with get_db() as conn:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? AND company IS NOT NULL AND TRIM(company) != ''",
            (user["id"],),
        ).fetchall()
        by_company: dict[str, dict[str, Any]] = {}
        for job in jobs:
            name = (job["company"] or "").strip()
            if not name:
                continue
            bucket = by_company.setdefault(
                name,
                {
                    "company": name,
                    "job_count": 0,
                    "scores": [],
                    "levels": {},
                    "jobs": [],
                },
            )
            bucket["job_count"] += 1
            latest = conn.execute(
                "SELECT score, level FROM match_runs WHERE job_id = ? ORDER BY version DESC LIMIT 1",
                (job["id"],),
            ).fetchone()
            score = None
            level = None
            if latest and latest["score"] is not None:
                score = latest["score"]
                level = latest["level"]
                bucket["scores"].append(score)
                if level:
                    bucket["levels"][level] = bucket["levels"].get(level, 0) + 1
            bucket["jobs"].append(
                {
                    "job_id": job["id"],
                    "title": job["title"],
                    "score": score,
                    "level": level,
                    "apply_status": job["apply_status"] or "待决策",
                    "starred": bool(job["starred"] or 0),
                }
            )

    items = []
    for name, b in by_company.items():
        scores = b["scores"]
        items.append(
            {
                "company": name,
                "job_count": b["job_count"],
                "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
                "levels": b["levels"],
                "jobs": b["jobs"],
            }
        )
    items.sort(key=lambda x: (-(x["avg_score"] or 0), -x["job_count"], x["company"]))
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


@router.patch("/jobs/{job_id}")
def patch_job(job_id: str, body: PatchJobBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "没有可更新的字段")
    if "apply_status" in fields and fields["apply_status"] not in APPLY_STATUSES:
        raise HTTPException(400, "无效的投递状态")

    with get_db() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, uid),
        ).fetchone()
        if not job:
            raise HTTPException(404, "岗位不存在")

        sets: list[str] = []
        vals: list[Any] = []
        old_status = job["apply_status"] or "待决策"
        for key in (
            "company",
            "location",
            "source_url",
            "employment_type",
            "title",
            "apply_status",
            "closed_reason",
        ):
            if key in fields:
                sets.append(f"{key} = ?")
                vals.append(fields[key])
        # 同步改正到 jd_profile 标签字段
        profile = loads(job["jd_profile_json"], {}) or {}
        for k in ("company", "location", "employment_type", "title"):
            if k in fields and fields[k] is not None:
                profile[k] = fields[k]
        if any(k in fields for k in ("company", "location", "employment_type", "title")):
            sets.append("jd_profile_json = ?")
            vals.append(dumps(profile))
        if "starred" in fields:
            sets.append("starred = ?")
            vals.append(1 if fields["starred"] else 0)
        sets.append("updated_at = ?")
        vals.append(utc_now())
        vals.extend([job_id, uid])
        conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
            vals,
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if "apply_status" in fields and fields["apply_status"] != old_status:
            conn.execute(
                """
                INSERT INTO application_status_history
                  (job_id, user_id, from_status, to_status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, uid, old_status, fields["apply_status"], utc_now()),
            )
        runs = conn.execute(
            "SELECT * FROM match_runs WHERE job_id = ? ORDER BY version DESC",
            (job_id,),
        ).fetchall()

    track_event("job_patch", {"job_id": job_id, "fields": list(fields.keys())}, user_id=uid)
    if "apply_status" in fields and fields["apply_status"] != old_status:
        track_event(
            "apply_status_change",
            {"job_id": job_id, "from": old_status, "to": fields["apply_status"]},
            user_id=uid,
        )
    return _job_out(row, [_match_out(r) for r in runs])


@router.post("/jobs/bulk-status")
def bulk_job_status(body: BulkJobStatusBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    now = utc_now()
    updated: list[str] = []
    with get_db() as conn:
        for job_id in dict.fromkeys(body.job_ids):
            row = conn.execute(
                "SELECT apply_status FROM jobs WHERE id=? AND user_id=?",
                (job_id, uid),
            ).fetchone()
            if not row:
                continue
            old = row["apply_status"] or "待决策"
            if old == body.apply_status:
                updated.append(job_id)
                continue
            conn.execute(
                "UPDATE jobs SET apply_status=?, updated_at=? WHERE id=? AND user_id=?",
                (body.apply_status, now, job_id, uid),
            )
            conn.execute(
                """
                INSERT INTO application_status_history
                  (job_id,user_id,from_status,to_status,created_at)
                VALUES (?,?,?,?,?)
                """,
                (job_id, uid, old, body.apply_status, now),
            )
            updated.append(job_id)
    track_event(
        "bulk_apply_status_change",
        {"count": len(updated), "to": body.apply_status},
        uid,
    )
    return {"updated_ids": updated, "count": len(updated)}


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


@router.get("/drafts")
def list_drafts(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM resume_drafts WHERE user_id=? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/drafts")
def create_draft(body: CreateDraftBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    now = utc_now()
    with get_db() as conn:
        match = _owned_match(conn, body.match_id, uid)
        if not match:
            raise HTTPException(404, "匹配记录不存在")
        draft_id = "d_" + uuid.uuid4().hex[:10]
        conn.execute(
            """
            INSERT INTO resume_drafts
              (id,user_id,resume_id,job_id,match_id,source_text,suggested_text,
               edited_text,source_label,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                draft_id,
                uid,
                match["resume_id"],
                match["job_id"],
                body.match_id,
                body.source_text,
                body.suggested_text,
                body.edited_text or body.suggested_text,
                body.source_label,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM resume_drafts WHERE id=?", (draft_id,)).fetchone()
    track_event("resume_draft_created", {"draft_id": draft_id, "match_id": body.match_id}, uid)
    return dict(row)


@router.patch("/drafts/{draft_id}")
def patch_draft(draft_id: str, body: PatchDraftBody, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE resume_drafts SET edited_text=?,updated_at=? WHERE id=? AND user_id=?",
            (body.edited_text, utc_now(), draft_id, user["id"]),
        )
        if not cur.rowcount:
            raise HTTPException(404, "草稿不存在")
        row = conn.execute("SELECT * FROM resume_drafts WHERE id=?", (draft_id,)).fetchone()
    return dict(row)


@router.put("/match/runs/{match_id}/action-item")
def set_action_item(
    match_id: str,
    body: ActionItemBody,
    user: dict = Depends(get_current_user),
):
    uid = user["id"]
    with get_db() as conn:
        if not _owned_match(conn, match_id, uid):
            raise HTTPException(404, "匹配记录不存在")
        conn.execute(
            """
            INSERT INTO report_action_items(match_id,user_id,item_key,completed,updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(match_id,user_id,item_key) DO UPDATE SET
              completed=excluded.completed, updated_at=excluded.updated_at
            """,
            (match_id, uid, body.item_key, 1 if body.completed else 0, utc_now()),
        )
    track_event(
        "report_action_item_change",
        {"match_id": match_id, "item_key": body.item_key, "completed": body.completed},
        uid,
    )
    return {"ok": True}


@router.get("/match/runs/{match_id}")
def get_match_run(match_id: str, user: dict = Depends(get_current_user)):
    """轮询判分/报告状态。"""
    with get_db() as conn:
        row = _owned_match(conn, match_id, user["id"])
        if not row:
            raise HTTPException(404, "匹配记录不存在")
        out = _match_out(row)
        if out.get("report"):
            resume = _fetch_resume(conn, out.get("resume_id"), user["id"])
            profile = loads(resume["profile_json"], {}) if resume else {}
            out["report"] = enrich_interview_preparation(out["report"], profile, out.get("jd_profile") or {})
        if isinstance(out.get("llm_meta"), dict) and out["llm_meta"].get("research"):
            out["llm_meta"]["research"] = clean_cached_research(out["llm_meta"]["research"])
        action_rows = conn.execute(
            "SELECT item_key,completed FROM report_action_items WHERE match_id=? AND user_id=?",
            (match_id, user["id"]),
        ).fetchall()
    return {
        "job_id": out["job_id"],
        "match_id": out["id"],
        "version": out["version"],
        "title": row["job_title"],
        "company": row["job_company"],
        "resume_id": out.get("resume_id"),
        "resume_name": out["resume_name"],
        "pref_name": out.get("pref_name") or "",
        "judge_status": out.get("judge_status"),
        "report_status": out.get("report_status"),
        "report_error": out.get("report_error"),
        "report_modules": out.get("report_modules"),
        "judge_duration_ms": out.get("judge_duration_ms"),
        "report_duration_ms": out.get("report_duration_ms"),
        "jd_profile": out.get("jd_profile"),
        "judge": _judge_payload(out),
        "report": out.get("report"),
        "llm": out.get("llm_meta"),
        "research": (out.get("llm_meta") or {}).get("research")
        if isinstance(out.get("llm_meta"), dict)
        else None,
        "starred": out.get("starred"),
        "batch_id": out.get("batch_id"),
        "recommended_action": out.get("recommended_action"),
        "action_summary": out.get("action_summary"),
        "completed_action_items": {
            r["item_key"]: bool(r["completed"]) for r in action_rows
        },
    }


def _start_report_for_match(
    match_id: str,
    uid: str,
    *,
    allow_statuses: set[str],
    bust_cache: bool,
    event_name: str,
) -> dict[str, Any]:
    with get_db() as conn:
        row = _owned_match(conn, match_id, uid)
        if not row:
            raise HTTPException(404, "匹配记录不存在")
        out = _match_out(row)
        if out.get("judge_status") != "done" and out.get("score") is None:
            raise HTTPException(400, "判分尚未完成，无法生成报告")
        status = out.get("report_status")
        if status == "running":
            return {
                "ok": True,
                "match_id": match_id,
                "report_status": "running",
                "message": "报告正在生成中",
            }
        if status not in allow_statuses and status != "running":
            raise HTTPException(400, f"当前报告状态为 {status}，不可触发生成")
        resume = _fetch_resume(conn, out["resume_id"], uid)
        if not resume or resume["status"] != "parsed":
            raise HTTPException(400, "关联简历不可用，无法生成报告")
        resume_profile = loads(resume["profile_json"], {})
        jd_profile = out.get("jd_profile") or {}
        judge = _judge_payload(out)
        jd_text = row["job_jd_text"] or ""
        conn.execute(
            """
            UPDATE match_runs SET report_status = ?, report_error = NULL,
              report_updated_at = ?, report_modules_json = ?, auto_report = 1
            WHERE id = ?
            """,
            (
                "pending",
                utc_now(),
                dumps({"m1": "pending", "m2": "pending", "m3": "pending", "m4": "pending"}),
                match_id,
            ),
        )

    _enqueue_report_job(
        match_id,
        uid,
        judge,
        resume_profile,
        jd_profile,
        jd_text,
        out["resume_id"],
        bust_cache=bust_cache,
    )
    track_event(event_name, {"match_id": match_id}, user_id=uid)
    return {"ok": True, "match_id": match_id, "report_status": "pending"}


@router.post("/match/runs/{match_id}/report")
def generate_match_report(match_id: str, user: dict = Depends(get_current_user)):
    """按需生成报告（批量默认 idle，或失败/排队中可触发）。"""
    return _start_report_for_match(
        match_id,
        user["id"],
        allow_statuses={"idle", "failed", "pending"},
        bust_cache=False,
        event_name="report_on_demand",
    )


@router.post("/match/runs/{match_id}/report/retry")
def retry_match_report(
    match_id: str,
    user: dict = Depends(get_current_user),
):
    """报告失败或用户显式重试：不重跑 Judge；并清除报告缓存。"""
    return _start_report_for_match(
        match_id,
        user["id"],
        allow_statuses={"idle", "failed", "pending", "done"},
        bust_cache=True,
        event_name="report_retry",
    )


@router.post("/match/runs/{match_id}/star")
def star_match_run(match_id: str, body: StarBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    with get_db() as conn:
        row = _owned_match(conn, match_id, uid)
        if not row:
            raise HTTPException(404, "匹配记录不存在")
        conn.execute(
            "UPDATE match_runs SET starred = ? WHERE id = ?",
            (1 if body.starred else 0, match_id),
        )
        # 同步岗位星标，便于列表筛选
        conn.execute(
            "UPDATE jobs SET starred = ?, updated_at = ? WHERE id = ?",
            (1 if body.starred else 0, utc_now(), row["job_id"]),
        )
    track_event(
        "match_star",
        {"match_id": match_id, "starred": body.starred},
        user_id=uid,
    )
    return {"ok": True, "match_id": match_id, "starred": body.starred}


@router.post("/match/extract-jd-url")
def extract_jd_url_api(body: ExtractJdUrlBody, user: dict = Depends(get_current_user)):
    """抽取岗位页。成功返回 JD；失败时若可降级则 200 + ok=false + source_url，便于前端建空卡片。"""
    t0 = time.time()
    try:
        result, meta = extract_jd_from_url(body.url)
    except Exception as exc:  # noqa: BLE001
        track_event(
            "url_extract_fail",
            {"error": str(exc)[:200]},
            user_id=user["id"],
        )
        raise HTTPException(400, f"链接抽取失败：{exc}") from exc

    ok = bool(result.get("ok")) and len(str(result.get("jd_text") or "").strip()) >= 20
    track_event(
        "url_extract_done" if ok else "url_extract_fail",
        {
            "success": ok,
            "duration_ms": int((time.time() - t0) * 1000),
            "llm_used": meta.get("used", False),
            "host": meta.get("host") or (meta.get("fetch") or {}).get("host"),
            "via": (meta.get("fetch") or {}).get("via"),
            "degraded": bool(result.get("degraded")),
            "reason": (result.get("notes") or meta.get("reason") or "")[:240],
            "fetch_error": (meta.get("error") or "")[:200],
        },
        user_id=user["id"],
    )
    payload = {
        "ok": ok,
        "jd_text": result.get("jd_text") or "",
        "title": result.get("title") or "",
        "company": result.get("company") or "",
        "location": result.get("location") or "",
        "employment_type": result.get("employment_type") or "",
        "source_url": result.get("source_url") or body.url,
        "notes": result.get("notes") or "",
        "degraded": bool(result.get("degraded")),
        "llm": meta,
    }
    if ok:
        return payload
    # 可降级：保留链接，让用户补 JD；纯非法 URL 仍 400
    if result.get("degraded") or result.get("source_url"):
        return payload
    raise HTTPException(400, result.get("notes") or "无法从该链接提取有效 JD")


@router.post("/match/recommend-resume")
def recommend_resume(body: RecommendResumeBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    resumes = _list_parsed_resumes(uid)
    if not resumes:
        raise HTTPException(400, "暂无已解析简历，请先上传")

    jd_profile, _meta = _resolve_jd_profile(body.jd_text, body.jd_profile)
    rough = [_recommend_one(r, body.jd_text, jd_profile, use_judge=False) for r in resumes]
    rough.sort(key=lambda x: x.get("score_estimate") or 0, reverse=True)
    by_id = {r["id"]: r for r in resumes}
    top_rows = [by_id[x["resume_id"]] for x in rough[:2]]
    judged_by_id: dict[str, dict[str, Any]] = {}
    # Top 2 并行真实 Judge；缓存命中时会立即返回，避免对所有简历完整判分。
    with ThreadPoolExecutor(max_workers=min(2, len(top_rows) or 1)) as executor:
        futures = {
            executor.submit(
                _recommend_one,
                row,
                body.jd_text,
                jd_profile,
                use_judge=True,
            ): row["id"]
            for row in top_rows
        }
        for future in as_completed(futures):
            judged_by_id[futures[future]] = future.result()
    ranked = [judged_by_id.get(x["resume_id"], x) for x in rough]
    ranked.sort(
        key=lambda x: (x.get("score_estimate") is not None, x.get("score_estimate") or 0),
        reverse=True,
    )
    if ranked:
        top_score = ranked[0].get("score_estimate") or 0
        for index, item in enumerate(ranked[:2]):
            item["rank"] = index + 1
            item["score_gap_to_top"] = max(0, top_score - (item.get("score_estimate") or 0))
        if len(ranked) > 1:
            ranked[0]["alternative"] = {
                "resume_id": ranked[1]["resume_id"],
                "name": ranked[1]["name"],
                "score_estimate": ranked[1].get("score_estimate"),
                "score_gap": ranked[1].get("score_gap_to_top"),
                "reason": ranked[1].get("reason"),
            }
    track_event(
        "resume_recommend",
        {"count": len(ranked), "judge_count": len(top_rows), "mode": "rough_top2_judge"},
        user_id=uid,
    )
    return {"items": ranked, "jd_profile": jd_profile, "mode": "rough_top2_judge"}


@router.post("/match/batch")
def batch_match(body: BatchMatchBody, user: dict = Depends(get_current_user)):
    uid = user["id"]
    if not body.items:
        raise HTTPException(400, "请至少提交 1 个岗位")
    if len(body.items) > 20:
        raise HTTPException(400, "单次批量最多 20 个岗位")

    fixed_resume = None
    fixed_profile = None
    if body.resume_id:
        with get_db() as conn:
            fixed_resume = _fetch_resume(conn, body.resume_id, uid)
        if not fixed_resume or fixed_resume["status"] != "parsed":
            raise HTTPException(400, "请选择已解析的简历")
        fixed_profile = loads(fixed_resume["profile_json"], {})

    batch_id = "b_" + uuid.uuid4().hex[:10]
    now = utc_now()
    total = len(body.items)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO match_batches (
              id, user_id, resume_id, status, total, done_count, failed_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                uid,
                body.resume_id,
                "running",
                total,
                0,
                0,
                now,
                now,
            ),
        )

    track_event(
        "batch_start",
        {
            "batch_id": batch_id,
            "total": total,
            "auto_report": body.auto_report,
            "auto_pick_resume": body.auto_pick_resume,
        },
        user_id=uid,
    )

    results: list[dict[str, Any]] = []
    done_count = 0
    failed_count = 0

    for idx, item in enumerate(body.items):
        try:
            resume_row = fixed_resume
            resume_profile = fixed_profile
            resume_id = body.resume_id

            if resume_row is None:
                if not body.auto_pick_resume:
                    raise HTTPException(400, "未指定简历且未开启自动选择")
                # 自动推荐：轻量重叠选最高分
                candidates = _list_parsed_resumes(uid)
                if not candidates:
                    raise HTTPException(400, "暂无已解析简历，请先上传")
                jd_profile_tmp, _ = _resolve_jd_profile(item.jd_text, None)
                best = None
                best_score = -1.0
                for r in candidates:
                    profile = loads(r["profile_json"], {}) or {}
                    score, _reason = _overlap_score(jd_profile_tmp, profile)
                    if score > best_score:
                        best_score = score
                        best = r
                resume_row = best
                resume_id = best["id"]
                resume_profile = loads(best["profile_json"], {})

            out = _run_match_core(
                uid=uid,
                jd_text=item.jd_text,
                resume_id=resume_id,
                resume_row=resume_row,
                resume_profile=resume_profile,
                company=item.company,
                location=item.location,
                source_url=item.source_url,
                employment_type=item.employment_type,
                batch_id=batch_id,
                auto_report=body.auto_report,
                title_override=item.title,
                track_start=False,
            )
            done_count += 1
            results.append({**out, "ok": True, "index": idx})
            track_event(
                "batch_item_done",
                {
                    "batch_id": batch_id,
                    "index": idx,
                    "match_id": out["match_id"],
                    "score": out["judge"].get("score"),
                    "ok": True,
                },
                user_id=uid,
            )
        except HTTPException as exc:
            failed_count += 1
            results.append(
                {
                    "ok": False,
                    "index": idx,
                    "error": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                }
            )
            track_event(
                "batch_item_done",
                {"batch_id": batch_id, "index": idx, "ok": False, "error": str(exc.detail)[:200]},
                user_id=uid,
            )
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            results.append({"ok": False, "index": idx, "error": str(exc)[:300]})
            track_event(
                "batch_item_done",
                {"batch_id": batch_id, "index": idx, "ok": False, "error": str(exc)[:200]},
                user_id=uid,
            )

        with get_db() as conn:
            conn.execute(
                """
                UPDATE match_batches SET done_count = ?, failed_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (done_count, failed_count, utc_now(), batch_id),
            )

    status = "done" if failed_count == 0 else ("partial" if done_count else "failed")
    with get_db() as conn:
        conn.execute(
            "UPDATE match_batches SET status = ?, done_count = ?, failed_count = ?, updated_at = ? WHERE id = ?",
            (status, done_count, failed_count, utc_now(), batch_id),
        )

    return {
        "batch_id": batch_id,
        "status": status,
        "total": total,
        "done_count": done_count,
        "failed_count": failed_count,
        "items": results,
    }


@router.get("/match/batches/{batch_id}")
def get_batch(batch_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        batch = conn.execute(
            "SELECT * FROM match_batches WHERE id = ? AND user_id = ?",
            (batch_id, user["id"]),
        ).fetchone()
        if not batch:
            raise HTTPException(404, "批次不存在")
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? AND batch_id = ? ORDER BY created_at ASC",
            (user["id"], batch_id),
        ).fetchall()
        job_outputs = {}
        for job in jobs:
            runs = conn.execute(
                "SELECT * FROM match_runs WHERE job_id = ? ORDER BY version DESC",
                (job["id"],),
            ).fetchall()
            job_outputs[job["id"]] = _job_out(job, [_match_out(r) for r in runs])
        batch_items = conn.execute(
            "SELECT * FROM match_batch_items WHERE batch_id=? ORDER BY item_index",
            (batch_id,),
        ).fetchall()
        items = []
        if batch_items:
            for item in batch_items:
                if item["job_id"] and item["job_id"] in job_outputs:
                    out = job_outputs[item["job_id"]]
                    out["item_index"] = item["item_index"]
                    out["batch_item_status"] = item["status"]
                    items.append(out)
                else:
                    raw = loads(item["input_json"], {}) or {}
                    items.append(
                        {
                            "ok": False,
                            "item_index": item["item_index"],
                            "batch_item_status": item["status"],
                            "title": raw.get("title") or f"岗位 {item['item_index'] + 1}",
                            "company": raw.get("company") or "",
                            "location": raw.get("location") or "",
                            "source_url": raw.get("source_url") or "",
                            "error": item["error"] or "",
                        }
                    )
        else:
            items = list(job_outputs.values())
    return {
        "batch": dict(batch),
        "items": items,
    }


def _run_persisted_batch(
    batch_id: str,
    uid: str,
    items: list[dict[str, Any]],
    resume_id: str | None,
    auto_pick_resume: bool,
    auto_report: bool,
) -> None:
    """后台执行已落库批次；单条完成即写库，前端可刷新恢复。"""
    fixed_resume = None
    fixed_profile = None
    if resume_id:
        with get_db() as conn:
            fixed_resume = _fetch_resume(conn, resume_id, uid)
        if fixed_resume:
            fixed_profile = loads(fixed_resume["profile_json"], {}) or {}
    done = 0
    failed = 0
    for idx, raw in enumerate(items):
        item = BatchItemBody(**raw)
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE match_batch_items SET status='running',updated_at=? WHERE batch_id=? AND item_index=?",
                    (utc_now(), batch_id, idx),
                )
            resume_row = fixed_resume
            resume_profile = fixed_profile
            selected_id = resume_id
            jd_profile_tmp = None
            if resume_row is None:
                if not auto_pick_resume:
                    raise ValueError("未指定简历且未开启自动选择")
                candidates = _list_parsed_resumes(uid)
                if not candidates:
                    raise ValueError("暂无已解析简历")
                jd_profile_tmp, _ = _resolve_jd_profile(item.jd_text, None)
                rough = []
                for candidate in candidates:
                    profile = loads(candidate["profile_json"], {}) or {}
                    score, _ = _overlap_score(jd_profile_tmp, profile)
                    rough.append((score, candidate, profile))
                rough.sort(key=lambda x: x[0], reverse=True)
                # Top 2 真实 Judge 并行，控制等待并提高自动选简历可信度。
                finalists = rough[:2]
                with ThreadPoolExecutor(max_workers=min(2, len(finalists))) as executor:
                    futures = {
                        executor.submit(
                            _resolve_judge,
                            row["id"],
                            item.jd_text,
                            jd_profile_tmp,
                            profile,
                        ): (row, profile)
                        for _, row, profile in finalists
                    }
                    judged = []
                    for future in as_completed(futures):
                        row, profile = futures[future]
                        judge, _ = future.result()
                        judged.append((judge.get("score") or 0, row, profile))
                judged.sort(key=lambda x: x[0], reverse=True)
                _, resume_row, resume_profile = judged[0]
                selected_id = resume_row["id"]
            out = _run_match_core(
                uid=uid,
                jd_text=item.jd_text,
                resume_id=selected_id,
                resume_row=resume_row,
                resume_profile=resume_profile,
                jd_profile_provided=jd_profile_tmp,
                company=item.company,
                location=item.location,
                source_url=item.source_url,
                employment_type=item.employment_type,
                batch_id=batch_id,
                auto_report=auto_report,
                title_override=item.title,
                track_start=False,
            )
            done += 1
            with get_db() as conn:
                conn.execute(
                    """
                    UPDATE match_batch_items SET status='done',job_id=?,error=NULL,updated_at=?
                    WHERE batch_id=? AND item_index=?
                    """,
                    (out["job_id"], utc_now(), batch_id, idx),
                )
            track_event("batch_item_done", {"batch_id": batch_id, "index": idx, "ok": True}, uid)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            with get_db() as conn:
                conn.execute(
                    """
                    UPDATE match_batch_items SET status='failed',error=?,updated_at=?
                    WHERE batch_id=? AND item_index=?
                    """,
                    (str(exc)[:300], utc_now(), batch_id, idx),
                )
            track_event(
                "batch_item_done",
                {"batch_id": batch_id, "index": idx, "ok": False, "error": str(exc)[:200]},
                uid,
            )
        with get_db() as conn:
            conn.execute(
                "UPDATE match_batches SET done_count=?, failed_count=?, updated_at=? WHERE id=?",
                (done, failed, utc_now(), batch_id),
            )
    status = "done" if failed == 0 else ("partial" if done else "failed")
    with get_db() as conn:
        conn.execute(
            "UPDATE match_batches SET status=?, done_count=?, failed_count=?, updated_at=? WHERE id=?",
            (status, done, failed, utc_now(), batch_id),
        )
    track_event("batch_done", {"batch_id": batch_id, "done": done, "failed": failed}, uid)


@router.post("/match/batch/submit")
def submit_batch(body: BatchMatchBody, user: dict = Depends(get_current_user)):
    """快速返回 batch_id，后台逐条判分。重复幂等由客户端请求键后续扩展。"""
    uid = user["id"]
    if body.request_key:
        with get_db() as conn:
            existing = conn.execute(
                "SELECT * FROM match_batches WHERE user_id=? AND request_key=?",
                (uid, body.request_key),
            ).fetchone()
        if existing:
            return {
                "batch_id": existing["id"],
                "status": existing["status"],
                "total": existing["total"],
                "idempotent_replay": True,
            }
    if body.resume_id:
        with get_db() as conn:
            resume = _fetch_resume(conn, body.resume_id, uid)
        if not resume or resume["status"] != "parsed":
            raise HTTPException(400, "请选择已解析的简历")
    batch_id = "b_" + uuid.uuid4().hex[:10]
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO match_batches
              (id,user_id,resume_id,status,total,done_count,failed_count,request_key,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                batch_id,
                uid,
                body.resume_id,
                "running",
                len(body.items),
                0,
                0,
                body.request_key,
                now,
                now,
            ),
        )
        for idx, item in enumerate(body.items):
            conn.execute(
                """
                INSERT INTO match_batch_items
                  (batch_id,item_index,input_json,status,updated_at)
                VALUES (?,?,?,?,?)
                """,
                (batch_id, idx, dumps(item.model_dump()), "queued", now),
            )
    track_event(
        "batch_start",
        {"batch_id": batch_id, "total": len(body.items), "async": True},
        uid,
    )
    thread = threading.Thread(
        target=_run_persisted_batch,
        args=(
            batch_id,
            uid,
            [x.model_dump() for x in body.items],
            body.resume_id,
            body.auto_pick_resume,
            body.auto_report,
        ),
        daemon=True,
        name=f"batch-{batch_id}",
    )
    thread.start()
    return {"batch_id": batch_id, "status": "running", "total": len(body.items)}


@router.post("/match/batches/{batch_id}/items/{item_index}/retry")
def retry_batch_item(
    batch_id: str,
    item_index: int,
    user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        batch = conn.execute(
            "SELECT * FROM match_batches WHERE id=? AND user_id=?",
            (batch_id, user["id"]),
        ).fetchone()
        item = conn.execute(
            "SELECT * FROM match_batch_items WHERE batch_id=? AND item_index=?",
            (batch_id, item_index),
        ).fetchone()
    if not batch or not item:
        raise HTTPException(404, "批次条目不存在")
    raw = loads(item["input_json"], {}) or {}
    body = BatchMatchBody(
        items=[BatchItemBody(**raw)],
        resume_id=batch["resume_id"],
        auto_pick_resume=not bool(batch["resume_id"]),
        auto_report=False,
        request_key=f"retry:{batch_id}:{item_index}:{uuid.uuid4().hex[:8]}",
    )
    track_event("batch_item_retry", {"batch_id": batch_id, "index": item_index}, user["id"])
    return submit_batch(body, user)


@router.post("/match/extract-jd-image")
async def extract_jd_image_api(
    file: UploadFile = File(...), user: dict = Depends(get_current_user),
):
    raise HTTPException(410, "为保护图片中的个人信息，云端识图已关闭。请粘贴岗位文本或使用公开招聘链接。")


@router.post("/match/analyze-jd")
def analyze_jd_api(body: AnalyzeJdBody, user: dict = Depends(get_current_user)):
    t0 = time.time()
    profile, meta = _resolve_jd_profile(body.jd_text, None)
    tags = job_tags_from_profile(profile, body.jd_text)
    track_event(
        "jd_analyze_done",
        {
            "success": True,
            "duration_ms": int((time.time() - t0) * 1000),
            "llm_used": meta.get("used", False),
            "cached": bool(meta.get("cached")),
        },
        user_id=user["id"],
    )
    return {
        "jd_profile": profile,
        "tags": tags,
        "llm": meta,
        "cached": bool(meta.get("cached")),
    }


@router.post("/match/research")
def research_api(body: ResearchBody, user: dict = Depends(get_current_user)):
    started = time.time()
    if body.match_id:
        with get_db() as conn:
            row = _owned_match(conn, body.match_id, user["id"])
            if not row:
                raise HTTPException(404, "匹配记录不存在")
            existing = clean_cached_research((loads(row["llm_meta_json"], {}) or {}).get("research") or {})
            if existing.get("research_version") == 5 and existing.get("status") in {"done", "demo"}:
                return {"research": existing, "llm": {"used": False, "cached": True}}
            job = conn.execute("SELECT company,title FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            body.company = job["company"] or body.company
            body.title = job["title"]
    result, meta = research_company(
        body.company.strip(), (body.title or "").strip(), (body.industry or "").strip()
    )
    if body.match_id:
        with get_db() as conn:
            conn.execute("UPDATE match_runs SET llm_meta_json=json_patch(COALESCE(llm_meta_json,'{}'),?) WHERE id=?",
                (dumps({"research": result, "research_meta": meta}), body.match_id))
    track_event(
        "company_research_done",
        {
            "company": body.company.strip(),
            "source_count": len(result.get("sources") or []),
            "duration_ms": int((time.time() - started) * 1000),
        },
        user_id=user["id"],
    )
    return {"research": result, "llm": meta}


@router.post("/match/split-jd")
def split_jd_api(body: SplitJdBody, user: dict = Depends(get_current_user)):
    """规则优先切分；仅边界可疑时调用 LLM，结果始终需要前端确认。"""
    raw = body.text.strip()
    explicit = [x.strip() for x in re.split(r"\n\s*---\s*\n", raw) if len(x.strip()) >= 20]
    if len(explicit) > 1:
        parts, confidence, method = explicit, 0.98, "规则"
    else:
        marked = [
            x.strip()
            for x in re.split(
                r"\n{2,}(?=(?:岗位|职位|招聘)(?:名称|标题|职位)?\s*[:：])",
                raw,
            )
            if len(x.strip()) >= 20
        ]
        marker_count = len(
            re.findall(r"(?:^|\n)(?:岗位|职位|招聘)(?:名称|标题|职位)?\s*[:：]", raw)
        )
        if len(marked) > 1:
            parts, confidence, method = marked, 0.9, "规则"
        elif marker_count < 2:
            parts, confidence, method = [raw], 0.85, "规则"
        else:
            from server.llm import llm

            fallback = {"items": [{"jd_text": raw}]}
            data, meta = llm.complete_json(
                "把输入切分为独立岗位 JD。普通段落空行不是边界。只输出 JSON："
                '{"items":[{"jd_text":"完整原文片段"}]}。不得改写或补充原文。',
                raw,
                fallback,
                model=llm.fast_model,
                max_tokens=3000,
                temperature=0,
                timeout=settings.llm_timeout_fast,
            )
            candidates = data.get("items") if isinstance(data, dict) else None
            parts = [
                str(x.get("jd_text") or "").strip()
                for x in (candidates or [])
                if isinstance(x, dict) and len(str(x.get("jd_text") or "").strip()) >= 20
            ] or [raw]
            confidence, method = (0.65 if meta.get("used") else 0.4), "LLM"
    track_event(
        "jd_split",
        {"count": len(parts), "method": method, "confidence": confidence},
        user["id"],
    )
    return {
        "items": [{"jd_text": part} for part in parts],
        "confidence": confidence,
        "split_method": method,
        "needs_confirmation": True,
    }


def _reuse_completed_match(uid: str, resume_id: str, jd_text: str, evidence_hash: str) -> dict[str, Any] | None:
    """Reuse a finished analysis for the same resume + JD (keeps demo presets instant)."""
    digest = text_hash(jd_text)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT mr.*, j.title AS job_title, j.company, j.location, j.employment_type
            FROM match_runs mr
            JOIN jobs j ON j.id = mr.job_id
            WHERE j.user_id = ? AND mr.resume_id = ? AND mr.jd_text_hash = ?
              AND mr.judge_status = 'done' AND mr.report_status = 'done'
            ORDER BY mr.created_at DESC
            LIMIT 1
            """,
            (uid, resume_id, digest),
        ).fetchone()
        if not row:
            return None
        out = _match_out(row)
        meta = out.get("llm_meta") or {}
        if not isinstance(meta, dict) or meta.get("resume_evidence_hash") != evidence_hash or meta.get("privacy_version") != 1 or meta.get("jd_parse_version") != 3:
            return None
        if not (out.get("report") or {}).get("interview_preparation"):
            return None
        if (meta.get("action") or {}).get("content_version") != 4:
            return None
        research = meta.get("research") if isinstance(meta, dict) else None
    return {
        "job_id": out["job_id"],
        "match_id": out["id"],
        "version": out["version"],
        "title": row["job_title"],
        "jd_profile": out.get("jd_profile"),
        "judge": _judge_payload(out),
        "report": out.get("report"),
        "resume_name": out.get("resume_name"),
        "resume_id": out.get("resume_id"),
        "llm": meta,
        "research": research,
        "judge_status": "done",
        "report_status": "done",
        "report_modules": out.get("report_modules"),
        "reused": True,
        "cached": {"jd": True, "judge": True},
        "recommended_action": out.get("recommended_action"),
        "company": row["company"] or "",
        "location": row["location"] or "",
        "employment_type": row["employment_type"] or "",
    }


@router.post("/match/run")
def run_match(
    body: RunMatchBody,
    user: dict = Depends(get_current_user),
):
    """判分完成后立即返回；完整报告按 auto_report 后台异步生成。"""
    uid = user["id"]
    with get_db() as conn:
        resume = _fetch_resume(conn, body.resume_id, uid)
        if not resume or resume["status"] != "parsed":
            raise HTTPException(400, "请选择已解析的简历")
        resume_profile = loads(resume["profile_json"], {})
    reused = None if body.jd_profile else _reuse_completed_match(uid, body.resume_id, body.jd_text,
                                   text_hash(dumps(resume_profile.get("resume_sections") or {})))
    if reused:
        return reused

    return _run_match_core(
        uid=uid,
        jd_text=body.jd_text,
        resume_id=body.resume_id,
        resume_row=resume,
        resume_profile=resume_profile,
        jd_profile_provided=body.jd_profile,
        job_id=body.job_id,
        company=body.company,
        location=body.location,
        source_url=body.source_url,
        employment_type=body.employment_type,
        batch_id=body.batch_id,
        starred=body.starred,
        auto_report=body.auto_report,
        track_start=True,
    )
