from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from server.llm import llm


def _search_rss(query: str, limit: int = 5) -> list[dict[str, str]]:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 OfferOS/2"})
    with urllib.request.urlopen(req, timeout=8) as response:
        root = ET.fromstring(response.read())
    items: list[dict[str, str]] = []
    for node in root.findall(".//item")[:limit]:
        link = (node.findtext("link") or "").strip()
        if link.startswith(("http://", "https://")):
            items.append({
                "title": (node.findtext("title") or "").strip(),
                "url": link,
                "snippet": (node.findtext("description") or "").strip()[:500],
                "published_at": (node.findtext("pubDate") or "").strip(),
            })
    return items


def research_company(company: str, title: str = "", industry: str = "") -> tuple[dict[str, Any], dict]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for query in (
        f"{company} 近半年 业务 动作",
        f"{company} 融资 估值",
        f"{industry or title or company} 行业 现状 2026",
    ):
        try:
            for item in _search_rss(query):
                if item["url"] not in seen:
                    seen.add(item["url"])
                    sources.append(item)
        except Exception:
            continue
    fallback = {
        "industry_status": [],
        "company_moves": [],
        "financing_valuation": [{
            "conclusion": "暂未检索到可核验的近期融资或估值信息",
            "source_ids": [],
            "confidence": "低",
        }],
        "research_note": "仅展示有来源支撑的信息；未检索到不代表不存在。",
    }
    if not sources:
        return {**fallback, "sources": []}, {"used": False, "reason": "no_sources"}
    system = """你是公司与行业研究员。只根据给定搜索结果形成结论，不得用记忆补充事实。
输出 JSON：{"industry_status":[{"conclusion":"结论","source_ids":[1],"confidence":"高|中|低"}],
"company_moves":[{"conclusion":"近半年业务动作","source_ids":[1],"confidence":"高|中|低"}],
"financing_valuation":[{"conclusion":"融资或估值；没有就明确未检索到","source_ids":[1],"confidence":"高|中|低"}],
"research_note":"信息边界"}。每条事实结论必须至少引用一个 source_id。"""
    data, meta = llm.complete_json(
        system,
        json.dumps({"company": company, "role": title, "sources": sources}, ensure_ascii=False),
        fallback,
        max_tokens=1400,
    )
    out = data if isinstance(data, dict) else fallback
    for section in ("industry_status", "company_moves", "financing_valuation"):
        clean = []
        for item in out.get(section) or []:
            ids = [i for i in item.get("source_ids", []) if isinstance(i, int) and 1 <= i <= len(sources)]
            if ids or "未检索到" in str(item.get("conclusion", "")):
                clean.append({**item, "source_ids": ids})
        out[section] = clean
    out["sources"] = [{"id": i + 1, **source} for i, source in enumerate(sources)]
    return out, meta
