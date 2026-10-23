"""从用户提交的岗位网页链接抽取 JD 信息（导入-only，非全站爬岗）。"""
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

from server.config import settings
from server.llm import llm
from server.agents.jd_agent import _infer_employment_type, _normalize_employment_type

EXTRACT_FROM_PAGE_SYSTEM = """你是招聘岗位信息提取助手。用户提供网页正文文本（可能含导航噪音）。
请抽取岗位信息，输出 JSON：
{
  "ok": true,
  "jd_text": "整理后的完整 JD（岗位名、公司、地点、职责、要求等，换行分段）",
  "title": "岗位标题",
  "company": "公司名（未知则空字符串）",
  "location": "城市/地区/远程（未知则空字符串）",
  "employment_type": "全职|实习|兼职|校园招聘|未知",
  "notes": "简短说明"
}
规则：
- 只基于给定文本，不要编造。
- 若几乎不是岗位页或信息不足，ok=false，jd_text 可空。
- 只输出 JSON。
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SITE_HINTS = (
    "zhipin.com",
    "bosszhipin",
    "lagou.com",
    "liepin.com",
    "51job.com",
    "zhaopin.com",
    "linkedin.com",
    "jobs.lever.co",
    "greenhouse.io",
    "boards.greenhouse.io",
    "nowcoder.com",
    "moka.com",
    "jobs.bytedance.com",
    "careers.tencent.com",
    "talent.alibaba.com",
)

ANTI_BOT_MARKERS = (
    "security verification",
    "access denied",
    "just a moment",
    "cf-browser-verification",
    "captcha",
    "人机验证",
    "安全验证",
    "请完成安全验证",
    "edgeone",
    "blocked",
    "robot",
)


def _normalize_url(url: str) -> str:
    u = (url or "").strip().strip("<>\"'").strip()
    # 去掉常见中文尾巴
    u = re.split(r"[\s\u3000]+", u, maxsplit=1)[0]
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def _is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _assert_public_url(url: str) -> None:
    """阻止链接抽取访问本机、内网和云元数据地址。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("仅支持公开的 HTTP/HTTPS 链接")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("不允许访问本机或内网地址")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("岗位链接域名无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("不允许访问本机、内网或保留地址")


def _strip_html(raw: str) -> str:
    text = raw
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    metas: list[str] = []
    for m in re.finditer(
        r'(?is)<meta[^>]+(?:property|name)=["\'](?:og:title|og:description|description|twitter:title|twitter:description)["\'][^>]+content=["\']([^"\']+)["\']',
        raw,
    ):
        metas.append(html.unescape(m.group(1)))
    for m in re.finditer(
        r'(?is)<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:title|og:description|description|twitter:title)["\']',
        raw,
    ):
        metas.append(html.unescape(m.group(1)))
    # JSON-LD JobPosting
    for m in re.finditer(
        r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw,
    ):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or ""
            desc = item.get("description") or ""
            org = item.get("hiringOrganization") or {}
            if isinstance(org, dict):
                company = org.get("name") or ""
            else:
                company = ""
            loc = ""
            jl = item.get("jobLocation") or {}
            if isinstance(jl, list) and jl:
                jl = jl[0]
            if isinstance(jl, dict):
                addr = jl.get("address") or {}
                if isinstance(addr, dict):
                    loc = addr.get("addressLocality") or addr.get("addressRegion") or ""
            chunk = "\n".join(
                x for x in [
                    f"岗位：{title}" if title else "",
                    f"公司：{company}" if company else "",
                    f"地点：{loc}" if loc else "",
                    html.unescape(re.sub(r"<[^>]+>", "\n", str(desc))),
                ] if x
            )
            if chunk.strip():
                metas.append(chunk.strip())

    title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if title_m:
        metas.insert(0, html.unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()))
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)</div>", "\n", text)
    text = re.sub(r"(?is)</li>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    body = text.strip()
    meta_block = "\n\n".join(dict.fromkeys([m for m in metas if m]))
    if meta_block:
        return (meta_block + "\n\n" + body)[:24000]
    return body[:24000]


def _looks_like_anti_bot(text: str) -> bool:
    low = (text or "").lower()
    if not low.strip():
        return False
    compact = re.sub(r"\s+", "", low)
    hits = sum(1 for m in ANTI_BOT_MARKERS if m in low)
    if hits >= 1 and len(compact) < 900:
        return True
    if "security verification" in low and len(compact) < 2000:
        return True
    return False


def fetch_page_text(url: str) -> tuple[str, dict[str, Any]]:
    """Anonymous public fetch, with redirect/DNS/size checks shared with discovery."""
    from server.public_fetch import fetch_public_page
    raw, final_url = fetch_public_page(url)
    text = _strip_html(raw)
    if len(re.sub(r"\s+", "", text)) < 80 or _looks_like_anti_bot(text):
        raise ValueError("招聘页面正文不足或需要访问验证，请粘贴公开JD文本。")
    return text, {"host": urlparse(final_url).netloc.lower(), "via": "public-ip-pinned", "final_url": final_url, "text_len": len(text)}


def _heuristic_extract(page_text: str, url: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    # markdown 标题
    title = ""
    for ln in lines[:15]:
        if ln.startswith("#"):
            title = ln.lstrip("#").strip()[:80]
            break
    if not title:
        title = lines[0][:80] if lines else ""
    company = ""
    location = ""
    joined = "\n".join(lines[:100])
    for pat in (
        r"公司[名称]?[：:]\s*([^\n]{2,40})",
        r"招聘企业[：:]\s*([^\n]{2,40})",
        r"hiringOrganization[^\n]{0,40}?([^\n]{2,40})",
        r"([^\n]{2,30})\s*招聘",
    ):
        m = re.search(pat, joined)
        if m:
            company = m.group(1).strip()[:40]
            break
    for pat in (
        r"(?:工作)?地点[：:]\s*([^\n]{2,30})",
        r"城市[：:]\s*([^\n]{2,30})",
        r"(北京|上海|广州|深圳|杭州|成都|武汉|南京|苏州|西安|远程|Remote)",
    ):
        m = re.search(pat, joined)
        if m:
            location = m.group(1).strip()
            break
    jd_text = "\n".join(lines[:160]).strip()
    ok = len(jd_text) >= 40
    host = urlparse(url).netloc
    return {
        "ok": ok,
        "jd_text": jd_text if ok else "",
        "title": title,
        "company": company,
        "location": location,
        "employment_type": _infer_employment_type(page_text),
        "notes": "规则抽取" if ok else f"页面文本不足或非岗位页（{host}）",
    }


def extract_jd_from_url(url: str) -> tuple[dict[str, Any], dict]:
    """返回 (result, llm_meta)。result 含 ok/jd_text/title/company/location/source_url/notes。"""
    normalized = _normalize_url(url)
    if not _is_http_url(normalized):
        return {
            "ok": False,
            "jd_text": "",
            "title": "",
            "company": "",
            "location": "",
            "source_url": url or "",
            "notes": "请输入有效的 http(s) 岗位链接",
            "degraded": False,
        }, {"used": False, "reason": "invalid_url"}
    try:
        _assert_public_url(normalized)
    except ValueError as exc:
        return {
            "ok": False,
            "jd_text": "",
            "title": "",
            "company": "",
            "location": "",
            "source_url": normalized,
            "notes": str(exc),
            "degraded": False,
        }, {"used": False, "reason": "blocked_url"}

    try:
        page_text, fetch_meta = fetch_page_text(normalized)
    except Exception as exc:  # noqa: BLE001
        # 降级：仍返回 source_url，前端可建空卡片让用户粘贴 JD
        return {
            "ok": False,
            "jd_text": "",
            "title": "",
            "company": "",
            "location": "",
            "source_url": normalized,
            "notes": str(exc)[:240],
            "degraded": True,
        }, {"used": False, "reason": "fetch_failed", "error": str(exc)[:200]}

    fallback = _heuristic_extract(page_text, normalized)
    host = fetch_meta.get("host") or urlparse(normalized).netloc.lower()
    site_boost = any(h in host for h in SITE_HINTS)

    data, meta = llm.complete_json(
        EXTRACT_FROM_PAGE_SYSTEM,
        f"来源 URL：{normalized}\n站点提示：{'常见招聘站' if site_boost else '通用网页'}\n\n网页文本：\n{page_text[:12000]}",
        fallback,
        model=llm.fast_model,
        max_tokens=900,
        temperature=0.1,
        timeout=settings.llm_timeout_fast,
    )
    if not isinstance(data, dict):
        data = fallback

    jd_text = str(data.get("jd_text") or fallback.get("jd_text") or "").strip()
    # LLM 若误判 ok=false 但文本够长，仍采用文本
    ok = len(jd_text) >= 20
    if not ok:
        jd_text = str(fallback.get("jd_text") or "").strip()
        ok = len(jd_text) >= 20

    result = {
        "ok": ok,
        "jd_text": jd_text if ok else "",
        "title": (data.get("title") or fallback.get("title") or "")[:120],
        "company": (data.get("company") or fallback.get("company") or "")[:80],
        "location": (data.get("location") or fallback.get("location") or "")[:80],
        "employment_type": _normalize_employment_type(
            data.get("employment_type") or fallback.get("employment_type"),
            jd_text or page_text,
        ),
        "source_url": normalized,
        "notes": data.get("notes") or fallback.get("notes") or "",
        "degraded": False,
    }
    meta = {**meta, "host": host, "site_boost": site_boost, "fetch": fetch_meta}
    return result, meta
