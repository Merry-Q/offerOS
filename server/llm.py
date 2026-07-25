from __future__ import annotations

import base64
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
        self.vision_model = settings.glm_vision_model
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

    def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.chat_completions_url(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

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
        try:
            payload = self._post_chat(body)
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

    def complete_json_vision(
        self,
        system_prompt: str,
        user_text: str,
        image_bytes: bytes,
        mime: str,
        fallback: Any,
    ) -> tuple[Any, dict]:
        """多模态 JSON 输出（截图识图）。失败时在 auto 模式返回 fallback；glm 模式抛错。"""
        if not self.enabled:
            return fallback, {
                "used": False,
                "reason": "未配置 GLM_API_KEY 或 llm_mode=mock，无法识图。",
            }

        mime = (mime or "image/png").split(";")[0].strip().lower()
        if mime not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            mime = "image/png"
        if mime == "image/jpg":
            mime = "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        model = self.vision_model or self.model

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            payload = self._post_chat(body)
            content = payload["choices"][0]["message"]["content"]
            data = safe_json_loads(content, fallback)
            return data, {"used": True, "model": model, "vision": True}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            if self.mode == "glm":
                raise RuntimeError(f"GLM 识图失败：HTTP {exc.code} {detail}") from exc
            return fallback, {
                "used": False,
                "reason": f"GLM 识图失败已 fallback：HTTP {exc.code}",
                "vision": True,
            }
        except Exception as exc:  # noqa: BLE001
            if self.mode == "glm":
                raise
            return fallback, {
                "used": False,
                "reason": f"GLM 识图失败已 fallback：{exc}",
                "vision": True,
            }


llm = LLMClient()
