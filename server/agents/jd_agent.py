from __future__ import annotations

import re
from typing import Any

from server.config import settings
from server.llm import llm


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
- core_requirements仅列必须胜任的核心职责与能力；nice_to_haves单列明确写有优先、加分、preferred等非必需条件，不能混入核心能力或重复列出。
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
        "must_haves": [line for line in lines if re.search(r"必须|硬性要求", line)][:6],
        "core_requirements": [line for line in bullets if "优先" not in line][:6],
        "nice_to_haves": [line for line in lines if "优先" in line][:4],
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
    # Read the same bounded complete JD as the verified discovery item.
    data, meta = llm.complete_json(
        SYSTEM,
        f"JD 文本：\n{(jd_text or '')[:16000]}",
        fallback,
        model=llm.fast_model,
        max_tokens=3200,
        temperature=0.1,
        timeout=max(25, settings.llm_timeout_fast),
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
