from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth import get_current_user
from server.config import settings
from server.db import dumps, get_db, loads, utc_now
from server.job_discovery import discover, quick_score, verify_job
from server.llm import llm
from server.privacy import CITIES, ROLES, model_signals
from server.routers.matches import _fetch_resume as _fetch_row, _run_match_core
from server.demo import DEMO_USERNAME

router = APIRouter(tags=["discovery"])
_slots = threading.BoundedSemaphore(2)
_analysis_slots = threading.BoundedSemaphore(2)


class SearchBody(BaseModel):
    resume_id: str
    city: str = Field("", max_length=20)
    role: str = Field("", max_length=30)
    recruitment_type: str = Field("", max_length=20)


def _fetch_resume(resume_id, uid):
    with get_db() as conn:
        row = _fetch_row(conn, resume_id, uid)
    if not row:
        raise HTTPException(404, "简历不存在")
    if row["status"] != "parsed":
        raise HTTPException(409, "请先完成简历解析")
    return row, loads(row["profile_json"], {})


def _owned(run_id, uid):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM job_discovery_runs WHERE id=? AND user_id=?", (run_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, "搜索记录不存在")
    return dict(row)


def _public(row):
    data = {key: row[key] for key in ("id", "resume_id", "status", "stage", "error", "created_at", "updated_at")}
    data["signals"] = loads(row["signals_json"], {})
    data["filters"] = loads(row["filters_json"], {})
    data["rejected"] = loads(row["errors_json"], [])
    data["stats"] = loads(row["stats_json"], {})
    data["items"] = [{k: v for k, v in job.items() if k != "jd_text"} for job in loads(row["items_json"], [])]
    return data


def _update(run_id, **fields):
    fields["updated_at"] = utc_now()
    with get_db() as conn:
        conn.execute("UPDATE job_discovery_runs SET " + ",".join(key + "=?" for key in fields) + " WHERE id=?", [*fields.values(), run_id])


def _worker(run_id, profile, filters, previous_jobs):
    item_ids = {}
    def items_with_ids(jobs):
        return [{**job, "id": item_ids.setdefault(job["url"], "found_" + uuid.uuid4().hex[:12])} for job in jobs[:settings.discovery_limit]]

    def save_snapshot(jobs, stats):
        _update(run_id, items_json=dumps(items_with_ids(jobs)), stats_json=dumps(stats))

    try:
        jobs, rejected, meta = discover(profile, filters, lambda stage: _update(run_id, stage=stage), snapshot=save_snapshot, previous_jobs=previous_jobs)
        _update(run_id, status="done", stage="done", items_json=dumps(items_with_ids(jobs)), errors_json=dumps(rejected), stats_json=dumps(meta.get("stats", {})))
    except Exception as exc:
        _update(run_id, status="failed", stage="failed", error=str(exc) if isinstance(exc, RuntimeError) else "搜索未完成，请重试。")
    finally:
        _slots.release()


@router.get("/discovery/profile/{resume_id}")
def discovery_profile(resume_id: str, user=Depends(get_current_user)):
    row, profile = _fetch_resume(resume_id, user["id"])
    return {"signals": model_signals(profile), "enabled": llm.enabled, "cities": CITIES, "roles": ROLES,
        "recruitment_types": ["社会招聘", "校园招聘", "实习"], "limit": settings.discovery_limit}


@router.get("/discovery/runs")
def list_runs(resume_id: str, user=Depends(get_current_user)):
    _fetch_resume(resume_id, user["id"])
    with get_db() as conn:
        rows = conn.execute("SELECT id,resume_id,status,stage,error,created_at,updated_at,filters_json,"
                            "json_array_length(items_json) AS item_count FROM job_discovery_runs "
                            "WHERE user_id=? AND resume_id=? ORDER BY rowid ASC", (user["id"], resume_id)).fetchall()
    return {"items": [{**{key: row[key] for key in ("id", "resume_id", "status", "stage", "error", "created_at", "updated_at", "item_count")},
                       "filters": loads(row["filters_json"], {}), "page": index}
                      for index, row in enumerate(rows, 1)]}


@router.post("/discovery/search")
def search_jobs(body: SearchBody, user=Depends(get_current_user)):
    if user["username"] == DEMO_USERNAME:
        raise HTTPException(409, "请先建立独立体验空间，再搜索岗位。")
    row, profile = _fetch_resume(body.resume_id, user["id"])
    if body.city not in ("", *CITIES) or body.role not in ("", *ROLES) or body.recruitment_type not in ("", "社会招聘", "校园招聘", "实习"):
        raise HTTPException(422, "请选择已有的城市、岗位方向和招聘类型")
    if not llm.enabled:
        raise HTTPException(503, "请配置本地 DASHSCOPE_API_KEY，将 LLM_MODE 设为 auto 后重启服务。")
    signals = model_signals(profile)
    if not signals["roles"] and not body.role and not signals["skills"]:
        raise HTTPException(422, "简历未识别到职业标签，请先选择一个岗位方向。")
    filters = {"city": body.city, "role": body.role, "recruitment_type": body.recruitment_type}
    run_id = "search_" + uuid.uuid4().hex
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, "当前搜索任务较多，请稍后再试。")
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute("SELECT id FROM job_discovery_runs WHERE user_id=? AND status='running'", (user["id"],)).fetchone()
            if active:
                raise HTTPException(409, "已有搜索正在运行，请等待当前结果。")
            previous = conn.execute("SELECT items_json FROM job_discovery_runs WHERE user_id=? AND resume_id=? ORDER BY rowid ASC", (user["id"], body.resume_id)).fetchall()
            previous_jobs = [job for saved in previous for job in loads(saved["items_json"], [])]
            now = utc_now()
            conn.execute("INSERT INTO job_discovery_runs(id,user_id,resume_id,status,stage,filters_json,signals_json,created_at,updated_at) VALUES(?,?,?,'running','queued',?,?,?,?)", (run_id, user["id"], body.resume_id, dumps(filters), dumps(signals), now, now))
        thread = threading.Thread(target=_worker, args=(run_id, profile, filters, previous_jobs), daemon=True)
        thread.start()
    except Exception:
        _slots.release()
        raise
    return _public(_owned(run_id, user["id"]))


@router.get("/discovery/runs/{run_id}")
def get_run(run_id: str, user=Depends(get_current_user)):
    return _public(_owned(run_id, user["id"]))


@router.post("/discovery/runs/{run_id}/items/{item_id}/analyze")
def analyze_discovered(run_id: str, item_id: str, user=Depends(get_current_user)):
    run = _owned(run_id, user["id"])
    if run["status"] == "running":
        raise HTTPException(409, "搜索仍在补充岗位，请等待完成后再分析。")
    item = next((item for item in loads(run["items_json"], []) if item["id"] == item_id), None)
    if not item:
        raise HTTPException(404, "岗位不存在")
    resume, profile = _fetch_resume(run["resume_id"], user["id"])
    if not _analysis_slots.acquire(blocking=False):
        raise HTTPException(429, "正在处理其他岗位，请稍后再试。")
    try:
        try:
            current = verify_job(item["url"])
        except ValueError as exc:
            raise HTTPException(409, "最新岗位核验失败：" + str(exc)) from None
        if current["company"] != item["company"] or current["title"] != item["title"]:
            raise HTTPException(409, "该链接的公司或职位已变化，请重新搜索。")
        result = _run_match_core(uid=user["id"], jd_text=current["jd_text"], resume_id=run["resume_id"],
            resume_row=resume, resume_profile=profile, company=current["company"], location=current["city"],
            source_url=current["url"], employment_type=current["recruitment_type"], title_override=current["title"], auto_report=True)
        provenance = {"quick_score": quick_score(current, profile)["score"], "checked_at": current["checked_at"], "url": current["url"], "score_version": "quick-v1"}
        with get_db() as conn:
            saved = conn.execute("SELECT llm_meta_json FROM match_runs WHERE id=?", (result["match_id"],)).fetchone()
            if saved:
                meta = loads(saved["llm_meta_json"], {})
                meta["discovery"] = provenance
                conn.execute("UPDATE match_runs SET llm_meta_json=? WHERE id=?", (dumps(meta), result["match_id"]))
        return {**result, "discovery": provenance, "jd_text": current["jd_text"]}
    finally:
        _analysis_slots.release()


def recover_interrupted_runs():
    with get_db() as conn:
        conn.execute("UPDATE job_discovery_runs SET status='failed',stage='failed',error='服务重启中断了搜索，请重新搜索。',updated_at=? WHERE status='running'", (utc_now(),))
