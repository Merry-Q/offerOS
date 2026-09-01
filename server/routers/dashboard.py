from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from server.auth import get_current_user
from server.db import get_db

router = APIRouter(tags=["dashboard"])
DEFAULT_USER_TIMEZONE = timezone(timedelta(hours=8))


def _local_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).astimezone(DEFAULT_USER_TIMEZONE).date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def _task(job: Any, match: Any | None) -> dict[str, Any]:
    status = job["apply_status"] or "待决策"
    report_status = match["report_status"] if match else None
    if report_status == "failed":
        action_type, label, priority = "retry_report", "重试报告", 1
    elif report_status == "done" and status == "待决策":
        action_type, label, priority = "view_report", "查看行动建议", 2
    elif status == "待改简历":
        action_type, label, priority = "rewrite_resume", "查看修改项", 3
    elif status == "待投":
        action_type, label, priority = "open_source", "去投递", 4
    elif status == "已投":
        action_type, label, priority = "prepare_interview", "开始备面", 5
    else:
        action_type, label, priority = "view_job", "继续处理", 9
    return {
        "job_id": job["id"],
        "match_id": match["id"] if match else None,
        "title": job["title"],
        "company": job["company"] or "",
        "status": status,
        "action_type": action_type,
        "action_label": label,
        "priority": priority,
        "source_url": job["source_url"] or "",
        "updated_at": job["updated_at"],
    }


@router.get("/dashboard")
def dashboard(user: dict = Depends(get_current_user)):
    uid = user["id"]
    today = datetime.now(DEFAULT_USER_TIMEZONE).date().isoformat()
    with get_db() as conn:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY updated_at DESC",
            (uid,),
        ).fetchall()
        batches = conn.execute(
            "SELECT * FROM match_batches WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (uid,),
        ).fetchone()
        tasks: list[dict[str, Any]] = []
        levels = Counter()
        judged_today = 0
        imported_today = 0
        for job in jobs:
            latest = conn.execute(
                "SELECT * FROM match_runs WHERE job_id = ? ORDER BY version DESC LIMIT 1",
                (job["id"],),
            ).fetchone()
            if _local_date(job["created_at"]) == today:
                imported_today += 1
            if latest:
                if _local_date(latest["created_at"]) == today:
                    judged_today += 1
                if latest["level"]:
                    levels[latest["level"]] += 1
            status = job["apply_status"] or "待决策"
            if status != "结束":
                tasks.append(_task(job, latest))

    status_counts = Counter((j["apply_status"] or "待决策") for j in jobs)
    tasks.sort(key=lambda x: x["updated_at"], reverse=True)
    tasks.sort(key=lambda x: x["priority"])
    return {
        "today": {
            "imported": imported_today,
            "judged": judged_today,
            "recommended": levels["保"] + levels["稳"] + levels["冲"],
            "todo_apply": status_counts["待投"],
            "applied": status_counts["已投"],
            "interviewing": status_counts["面试中"],
        },
        "status_counts": dict(status_counts),
        "tasks": tasks[:5],
        "latest_batch": dict(batches) if batches else None,
    }
