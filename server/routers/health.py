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
    onboarded = parsed > 0
    return {
        "ok": True,
        "llm_configured": settings.llm_configured,
        "llm_mode": settings.llm_mode,
        "model": settings.glm_model,
        "base_url": settings.glm_base_url,
        "onboarded": onboarded,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
        "counts": {"resumes": resumes, "parsed_resumes": parsed},
    }
