from __future__ import annotations

import re
from typing import Any

from server.llm import llm


SYSTEM = """你是 JD Analyst Agent。分析岗位 JD，输出 JSON：
{
  "title": "岗位标题",
  "level": "级别推断",
  "must_haves": ["强制门槛..."],
  "core_requirements": ["核心要求..."],
  "nice_to_haves": ["加分项..."],
  "risks": ["JD 风险/坑..."],
  "summary": "一句话岗位档案"
}
只输出 JSON。不要编造 JD 未写的硬性门槛。"""

EXTRACT_SYSTEM = """你是招聘信息提取助手。用户会提供一张岗位 JD 截图。
请识别图中文字，整理为可编辑的岗位描述文本，并输出 JSON：
{
  "jd_text": "从截图提取并整理后的完整 JD 文本（保留岗位名、职责、要求、加分项等关键信息，用换行分段）",
  "title": "岗位标题（若能识别）",
  "ok": true,
  "notes": "简短说明：是否清晰、是否有遮挡/截断"
}
规则：
- 只提取图中可见内容，不要编造。
- 若几乎无法识别岗位信息，ok 设为 false，jd_text 可为空，notes 说明原因。
- 只输出 JSON。"""


def mock_jd_profile(jd_text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in jd_text.splitlines() if ln.strip()]
    title = lines[0] if lines else "未命名岗位"
    title = re.sub(r"^岗位[：:]\s*", "", title)[:60]
    bullets = [re.sub(r"^[\d\-、\.\)\s]+", "", ln) for ln in lines[1:8] if len(ln) > 4]
    return {
        "title": title,
        "level": "未知",
        "must_haves": bullets[:2] or ["具备相关岗位经验"],
        "core_requirements": bullets[2:5] or ["能独立推进核心任务"],
        "nice_to_haves": bullets[5:7],
        "risks": ["JD 表述可能偏理想化，需用证据核验「独立负责」类要求"],
        "summary": f"{title} · 规则拆解岗位档案",
    }


def analyze_jd(jd_text: str) -> tuple[dict[str, Any], dict]:
    fallback = mock_jd_profile(jd_text)
    data, meta = llm.complete_json(SYSTEM, f"JD 文本：\n{jd_text[:10000]}", fallback)
    if not isinstance(data, dict):
        return fallback, meta
    if not data.get("title"):
        data["title"] = fallback["title"]
    return data, meta


def extract_jd_from_image(image_bytes: bytes, mime: str) -> tuple[dict[str, Any], dict]:
    fallback = {
        "jd_text": "",
        "title": "",
        "ok": False,
        "notes": "未能识别截图中的岗位信息，请重传更清晰的截图",
    }
    data, meta = llm.complete_json_vision(
        EXTRACT_SYSTEM,
        "请提取这张 JD 截图中的岗位信息。",
        image_bytes,
        mime,
        fallback,
    )
    if not isinstance(data, dict):
        return fallback, meta

    jd_text = str(data.get("jd_text") or "").strip()
    ok = bool(data.get("ok", True)) and len(jd_text) >= 20
    result = {
        "jd_text": jd_text,
        "title": str(data.get("title") or "").strip(),
        "ok": ok,
        "notes": str(data.get("notes") or "").strip(),
    }
    if not ok and not result["notes"]:
        result["notes"] = "识别结果过短或无效，请重传截图"
    return result, meta
