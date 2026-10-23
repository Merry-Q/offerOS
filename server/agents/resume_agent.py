from __future__ import annotations

from typing import Any

from server.resume_evidence import attach_resume_evidence


def analyze_resume(raw_text: str, file_name: str) -> tuple[dict[str, Any], dict]:
    meta = {"used": False, "local": True, "reason": "本地解析；简历原文和文件名不发送给模型。"}
    return attach_resume_evidence({}, raw_text, meta=meta), meta
