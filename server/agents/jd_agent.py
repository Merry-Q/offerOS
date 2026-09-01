from __future__ import annotations

import re
from typing import Any

from server.config import settings
from server.llm import llm, split_image_for_ocr


SYSTEM = """你是 JD Analyst Agent。分析岗位 JD，输出 JSON：
{
  "title": "岗位标题",
  "company": "公司名（JD 未写则空字符串）",
  "location": "城市/地区/远程（未写则空字符串）",
  "employment_type": "全职|实习|兼职|校园招聘|未知",
  "level": "级别推断（如 初级/高级/P6/未知）",
  "hard_gates": {
    "major": {"requirement":"专业要求","strictness":"必须对口|相关即可|未要求"},
    "education": {"requirement":"学历要求","strictness":"硬性|偏好|未要求"},
    "experience": {"requirement":"经验要求","strictness":"硬性|偏好|未要求"},
    "language": {"requirement":"语言要求","strictness":"硬性|偏好|未要求"}
  },
  "must_haves": ["强制门槛..."],
  "core_requirements": ["核心要求..."],
  "nice_to_haves": ["加分项..."],
  "risks": ["JD 风险/坑..."],
  "summary": "一句话岗位档案"
}
规则：
- company/location/employment_type 只依据 JD 可见信息，不要编造。
- employment_type：出现实习/intern→实习；兼职/part-time→兼职；校招/应届→校园招聘；否则倾向全职；实在看不出→未知。
- 不要编造 JD 未写的硬性门槛。
只输出 JSON。"""


EMPLOYMENT_TYPES = ("全职", "实习", "兼职", "校园招聘", "未知")


def _infer_employment_type(jd_text: str) -> str:
    t = (jd_text or "").lower()
    raw = jd_text or ""
    if re.search(r"实习|intern", raw, re.I) or "intern" in t:
        return "实习"
    if re.search(r"兼职|part[\s\-]?time", raw, re.I):
        return "兼职"
    if re.search(r"校招|校园招聘|应届|毕业生", raw):
        return "校园招聘"
    if re.search(r"全职|正式编制|social\s*recruit", raw, re.I):
        return "全职"
    return "未知"


def _infer_company(jd_text: str) -> str:
    for pat in (
        r"公司[名称]?[：:]\s*([^\n]{2,40})",
        r"招聘企业[：:]\s*([^\n]{2,40})",
        r"^([^\n]{2,24})\s*招聘",
    ):
        m = re.search(pat, jd_text or "", re.M)
        if m:
            return m.group(1).strip()[:40]
    return ""


def _infer_location(jd_text: str) -> str:
    for pat in (
        r"(?:工作)?地点[：:]\s*([^\n]{2,30})",
        r"城市[：:]\s*([^\n]{2,30})",
        r"(北京|上海|广州|深圳|杭州|成都|武汉|南京|苏州|西安|远程|Remote)",
    ):
        m = re.search(pat, jd_text or "", re.I)
        if m:
            return m.group(1).strip()[:40]
    return ""


def mock_jd_profile(jd_text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in jd_text.splitlines() if ln.strip()]
    title = lines[0] if lines else "未命名岗位"
    title = re.sub(r"^岗位[：:]\s*", "", title)[:60]
    bullets = [re.sub(r"^[\d\-、\.\)\s]+", "", ln) for ln in lines[1:8] if len(ln) > 4]
    return {
        "title": title,
        "company": _infer_company(jd_text),
        "location": _infer_location(jd_text),
        "employment_type": _infer_employment_type(jd_text),
        "level": "未知",
        "hard_gates": {
            "major": {"requirement": "", "strictness": "未要求"},
            "education": {"requirement": "", "strictness": "未要求"},
            "experience": {"requirement": "", "strictness": "未要求"},
            "language": {"requirement": "", "strictness": "未要求"},
        },
        "must_haves": bullets[:2] or ["具备相关岗位经验"],
        "core_requirements": bullets[2:5] or ["能独立推进核心任务"],
        "nice_to_haves": bullets[5:7],
        "risks": ["JD 表述可能偏理想化，需用证据核验「独立负责」类要求"],
        "summary": f"{title} · 规则拆解岗位档案",
    }


def _normalize_employment_type(value: Any, jd_text: str = "") -> str:
    s = str(value or "").strip()
    if s in EMPLOYMENT_TYPES:
        return s
    # 容错映射
    low = s.lower()
    if "实习" in s or "intern" in low:
        return "实习"
    if "兼职" in s or "part" in low:
        return "兼职"
    if "校" in s or "应届" in s:
        return "校园招聘"
    if "全职" in s or "正式" in s:
        return "全职"
    return _infer_employment_type(jd_text)


def analyze_jd(jd_text: str) -> tuple[dict[str, Any], dict]:
    fallback = mock_jd_profile(jd_text)
    # 快模型 + 截断输入 + 限输出：目标 3–5s
    data, meta = llm.complete_json(
        SYSTEM,
        f"JD 文本：\n{(jd_text or '')[:5000]}",
        fallback,
        model=llm.fast_model,
        max_tokens=800,
        temperature=0.1,
        timeout=settings.llm_timeout_fast,
        disable_thinking=True,
    )
    if not isinstance(data, dict):
        return fallback, meta
    if not data.get("title"):
        data["title"] = fallback["title"]
    data["company"] = (data.get("company") or fallback.get("company") or "").strip()[:80]
    data["location"] = (data.get("location") or fallback.get("location") or "").strip()[:80]
    data["employment_type"] = _normalize_employment_type(
        data.get("employment_type"), jd_text
    )
    if not data.get("level"):
        data["level"] = fallback.get("level") or "未知"
    if not isinstance(data.get("hard_gates"), dict):
        data["hard_gates"] = fallback["hard_gates"]
    for key in ("must_haves", "core_requirements", "nice_to_haves", "risks"):
        if not isinstance(data.get(key), list):
            data[key] = fallback.get(key) or []
    return data, meta


def job_tags_from_profile(profile: dict | None, jd_text: str = "") -> dict[str, str]:
    """从 JD 档案抽出匹配库筛选用标签。"""
    p = profile or {}
    return {
        "title": (p.get("title") or "").strip()[:120] or "未命名岗位",
        "company": (p.get("company") or "").strip()[:80],
        "location": (p.get("location") or "").strip()[:80],
        "employment_type": _normalize_employment_type(p.get("employment_type"), jd_text),
        "level": (p.get("level") or "").strip()[:40] or "未知",
    }


EXTRACT_SYSTEM = """你是招聘信息提取助手。用户会提供一张岗位 JD 截图（可能来自 Boss/拉勾/猎聘/公司官网）。
请尽量完整识别图中可见文字，整理为可编辑的岗位描述，并只输出 JSON：
{
  "jd_text": "完整 JD 文本：含岗位名、公司、地点、薪资（若有）、职责、要求、加分项；用换行分段",
  "title": "岗位标题（若能识别，否则空字符串）",
  "company": "公司名（若能识别，否则空字符串）",
  "location": "城市/地区（若能识别，否则空字符串）",
  "ok": true,
  "notes": "一句说明：清晰度/是否截断/遮挡"
}
规则：
- 只提取图中可见内容，不要编造；看不清的字用…占位。
- 优先保证 jd_text 完整可用（至少包含职责或要求之一）。
- 若几乎无法识别岗位信息，ok=false，jd_text 可空，notes 说明原因。
- 只输出 JSON。"""


def extract_jd_from_image(image_bytes: bytes, mime: str) -> tuple[dict[str, Any], dict]:
    fallback = {
        "jd_text": "",
        "title": "",
        "company": "",
        "location": "",
        "ok": False,
        "notes": "未能识别截图中的岗位信息，请重传更清晰的截图",
    }
    tiles = split_image_for_ocr(image_bytes, mime)
    parts: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    for index, (tile_bytes, tile_mime) in enumerate(tiles):
        data_part, meta_part = llm.complete_json_vision(
            EXTRACT_SYSTEM,
            (
                f"这是同一份 JD 长截图的第 {index + 1}/{len(tiles)} 片。"
                "请提取本片所有可见文字，保留职责与任职要求原文结构；不要因为缺少标题而判失败。"
            ),
            tile_bytes,
            tile_mime,
            fallback,
            max_tokens=2500,
            timeout=max(settings.llm_timeout_default, 90),
        )
        metas.append(meta_part)
        if isinstance(data_part, dict) and str(data_part.get("jd_text") or "").strip():
            parts.append(data_part)
    if parts:
        seen_lines: set[str] = set()
        merged_lines: list[str] = []
        for part in parts:
            for line in str(part.get("jd_text") or "").replace("\\n", "\n").splitlines():
                clean = line.strip()
                key = re.sub(r"\s+", "", clean)
                if not clean or key in seen_lines:
                    continue
                seen_lines.add(key)
                merged_lines.append(clean)
        first = parts[0]
        data = {
            "ok": True,
            "jd_text": "\n".join(merged_lines),
            "title": next((str(x.get("title") or "").strip() for x in parts if x.get("title")), ""),
            "company": next((str(x.get("company") or "").strip() for x in parts if x.get("company")), ""),
            "location": next((str(x.get("location") or "").strip() for x in parts if x.get("location")), ""),
            "notes": f"已按原始清晰度识别并合并 {len(tiles)} 个分片"
            if len(tiles) > 1
            else str(first.get("notes") or ""),
        }
    else:
        data = fallback
    used_meta = next((x for x in metas if x.get("used")), metas[0] if metas else {})
    meta = {
        **used_meta,
        "tiles": len(tiles),
        "tile_results": [
            {
                "used": bool(x.get("used")),
                "model": x.get("model"),
                "reason": x.get("reason"),
                "parse_degraded": bool(x.get("parse_degraded")),
            }
            for x in metas
        ],
    }
    if not isinstance(data, dict):
        notes = meta.get("reason") or fallback["notes"]
        return {**fallback, "notes": notes}, meta

    jd_text = str(data.get("jd_text") or "").strip()
    # 有些模型把换行写成字面 \\n
    if "\\n" in jd_text and "\n" not in jd_text:
        jd_text = jd_text.replace("\\n", "\n")
    ok = bool(data.get("ok", True)) and len(jd_text) >= 20
    result = {
        "jd_text": jd_text,
        "title": str(data.get("title") or "").strip(),
        "company": str(data.get("company") or "").strip(),
        "location": str(data.get("location") or "").strip(),
        "ok": ok,
        "notes": str(data.get("notes") or "").strip(),
    }
    if not meta.get("used") and meta.get("reason"):
        result["ok"] = False
        result["notes"] = str(meta["reason"])
    elif not ok and not result["notes"]:
        result["notes"] = "识别结果过短或无效，请重传截图或改为粘贴文本"
    return result, meta
