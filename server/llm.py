from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from server.config import settings


def safe_json_loads(content: str, fallback: Any) -> Any:
    content = (content or "").strip()
    if not content:
        return fallback
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return fallback
        return fallback


class LLMClient:
    def __init__(self) -> None:
        self.api_key = settings.glm_api_key.strip()
        self.base_url = settings.glm_base_url.rstrip("/")
        self.model = settings.glm_model
        self.mode = (settings.llm_mode or "auto").lower()

    @property
    def enabled(self) -> bool:
        if self.mode == "mock":
            return False
        if not settings.llm_configured:
            return False
        if self.mode == "glm":
            return True
        return True

    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def complete_json(self, system_prompt: str, user_prompt: str, fallback: Any) -> tuple[Any, dict]:
        if not self.enabled:
            return fallback, {"used": False, "reason": "未配置 GLM_API_KEY 或 llm_mode=mock，使用规则/Mock。"}

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            self.chat_completions_url(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            data = safe_json_loads(content, fallback)
            return data, {"used": True, "model": self.model}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            if self.mode == "glm":
                raise RuntimeError(f"GLM API 失败：HTTP {exc.code} {detail}") from exc
            return fallback, {"used": False, "reason": f"GLM 失败已 fallback：HTTP {exc.code}"}
        except Exception as exc:  # noqa: BLE001
            if self.mode == "glm":
                raise
            return fallback, {"used": False, "reason": f"GLM 失败已 fallback：{exc}"}


llm = LLMClient()
