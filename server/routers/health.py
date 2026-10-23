from fastapi import APIRouter, Depends

from server.auth import get_current_user
from server.config import settings
from server.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(user: dict = Depends(get_current_user)):
    uid = user["id"]
    with get_db() as conn:
        resumes = conn.execute(
            "SELECT COUNT(*) AS c FROM resumes WHERE user_id = ?", (uid,)
        ).fetchone()["c"]
        parsed = conn.execute(
            "SELECT COUNT(*) AS c FROM resumes WHERE status = 'parsed' AND user_id = ?",
            (uid,),
        ).fetchone()["c"]
    # onboarded = 用户自己的已解析简历（不含共享示例）
    onboarded = parsed > 0
    return {
        "ok": True,
        "llm_configured": settings.llm_configured,
        "llm_mode": settings.llm_mode,
        "model": settings.qwen_model,
        "fast_model": settings.qwen_fast_model,
        "action_model": settings.qwen_action_model,
        "vision_ready": False,
        "input_pipeline_version": "public-jd-v1",
        "base_url": settings.dashscope_base_url,
        "onboarded": onboarded,
        "has_sample": True,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
        "counts": {"resumes": resumes, "parsed_resumes": parsed},
    }
