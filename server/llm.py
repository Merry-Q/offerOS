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


def sniff_image_mime(image_bytes: bytes, declared: str | None = None) -> str:
    """根据文件头识别图片 MIME，避免剪贴板/上传缺 type。"""
    declared = (declared or "").split(";")[0].strip().lower()
    if declared == "image/jpg":
        declared = "image/jpeg"
    if len(image_bytes) >= 12:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        if image_bytes[4:8] == b"ftyp":  # HEIC/HEIF
            return "image/heic"
    if declared in {"image/png", "image/jpeg", "image/webp"}:
        return declared
    return "image/png"


class LLMClient:
    def __init__(self) -> None:
        self.api_key = settings.glm_api_key.strip()
        self.base_url = settings.glm_base_url.rstrip("/")
        self.model = settings.glm_model
        self.fast_model = settings.glm_fast_model
        self.action_model = settings.glm_action_model
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

    def _post_chat(self, body: dict[str, Any], timeout: int) -> dict[str, Any]:
        req = urllib.request.Request(
            self.chat_completions_url(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _build_body(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        disable_thinking: bool | None,
        response_format_json: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format_json:
            body["response_format"] = {"type": "json_object"}
        if max_tokens is not None and max_tokens > 0:
            body["max_tokens"] = max_tokens
        # 关闭深度思考以降低延迟（不支持的模型通常会忽略或由上层 fallback）
        use_disable = (
            settings.llm_disable_thinking if disable_thinking is None else disable_thinking
        )
        if use_disable:
            body["thinking"] = {"type": "disabled"}
        return body

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: Any,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        timeout: int | None = None,
        disable_thinking: bool | None = None,
    ) -> tuple[Any, dict]:
        if not self.enabled:
            return fallback, {
                "used": False,
                "reason": "未配置 GLM_API_KEY 或 llm_mode=mock，使用规则/Mock。",
            }

        use_model = (model or self.model).strip() or self.model
        use_timeout = timeout or settings.llm_timeout_default
        body = self._build_body(
            model=use_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            disable_thinking=disable_thinking,
        )
        try:
            payload = self._post_chat(body, use_timeout)
            content = payload["choices"][0]["message"]["content"]
            data = safe_json_loads(content, fallback)
            return data, {
                "used": True,
                "model": use_model,
                "max_tokens": max_tokens,
                "timeout": use_timeout,
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            # 指定快模型不可用时，回退到主模型再试一次
            if use_model != self.model and exc.code in {400, 404}:
                body["model"] = self.model
                try:
                    payload = self._post_chat(body, use_timeout)
                    content = payload["choices"][0]["message"]["content"]
                    data = safe_json_loads(content, fallback)
                    return data, {
                        "used": True,
                        "model": self.model,
                        "max_tokens": max_tokens,
                        "timeout": use_timeout,
                        "fallback_from": use_model,
                    }
                except Exception:  # noqa: BLE001
                    pass
            # thinking 字段不被支持时，去掉后重试一次
            if "thinking" in body and exc.code in {400, 422}:
                body.pop("thinking", None)
                try:
                    payload = self._post_chat(body, use_timeout)
                    content = payload["choices"][0]["message"]["content"]
                    data = safe_json_loads(content, fallback)
                    return data, {
                        "used": True,
                        "model": body.get("model", use_model),
                        "max_tokens": max_tokens,
                        "timeout": use_timeout,
                        "thinking_stripped": True,
                    }
                except Exception as retry_exc:  # noqa: BLE001
                    if self.mode == "glm":
                        raise RuntimeError(
                            f"GLM API 失败：HTTP {exc.code} {detail}; retry={retry_exc}"
                        ) from retry_exc
                    return fallback, {
                        "used": False,
                        "reason": f"GLM 失败已 fallback：HTTP {exc.code}",
                    }
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
        *,
        max_tokens: int | None = 2500,
        timeout: int | None = None,
    ) -> tuple[Any, dict]:
        """多模态 JSON 输出（截图识图）。失败时在 auto 模式返回 fallback；glm 模式抛错。"""
        if self.mode == "mock":
            return fallback, {
                "used": False,
                "reason": "当前 LLM_MODE=mock，识图已关闭。请改为 auto 或 glm。",
                "vision": True,
            }
        if not settings.llm_configured:
            return fallback, {
                "used": False,
                "reason": "未配置有效 GLM_API_KEY，无法识图。",
                "vision": True,
            }
        if not self.enabled:
            return fallback, {
                "used": False,
                "reason": "LLM 未启用，无法识图。",
                "vision": True,
            }

        mime = sniff_image_mime(image_bytes, mime)
        if mime == "image/heic":
            return fallback, {
                "used": False,
                "reason": "暂不支持 HEIC，请先转为 PNG/JPG 再上传。",
                "vision": True,
            }
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            mime = "image/png"

        # 过大图容易超时/被拒：缩到合理体积（无 Pillow 时跳过）
        image_bytes, mime = _maybe_downscale_image(image_bytes, mime)

        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        model = (self.vision_model or self.model).strip() or self.model
        use_timeout = timeout or max(settings.llm_timeout_default, 90)

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]

        def _call(body: dict[str, Any]) -> tuple[Any, dict]:
            payload = self._post_chat(body, use_timeout)
            content = payload["choices"][0]["message"]["content"]
            data = safe_json_loads(content, fallback)
            meta = {
                "used": True,
                "model": body.get("model", model),
                "vision": True,
                "mime": mime,
                "bytes": len(image_bytes),
            }
            # 部分视觉模型能正确 OCR，但不遵守 JSON response_format。
            # 不应把可读文字误报成“图片不清晰”，降级为纯文本 OCR 结果供用户校对。
            if data is fallback and isinstance(content, str) and len(content.strip()) >= 20:
                plain = re.sub(r"^```(?:json|text)?\s*|\s*```$", "", content.strip(), flags=re.I)
                data = {
                    "ok": True,
                    "jd_text": plain,
                    "title": "",
                    "company": "",
                    "location": "",
                    "notes": "模型返回了非结构化 OCR 文字，已保留原文，请核对",
                }
                meta["parse_degraded"] = True
            return data, meta

        body = self._build_body(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
            disable_thinking=True,
            response_format_json=True,
        )
        try:
            return _call(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            # 逐级降级：去掉 thinking → 去掉 response_format → 换主模型
            retries: list[tuple[str, dict[str, Any]]] = []
            if "thinking" in body:
                b2 = dict(body)
                b2.pop("thinking", None)
                retries.append(("thinking_stripped", b2))
            if body.get("response_format"):
                b3 = dict(body)
                b3.pop("thinking", None)
                b3.pop("response_format", None)
                retries.append(("no_response_format", b3))
            if model != self.model:
                b4 = dict(body)
                b4.pop("thinking", None)
                b4["model"] = self.model
                retries.append(("fallback_model", b4))

            last_detail = detail
            for tag, retry_body in retries:
                try:
                    data, meta = _call(retry_body)
                    meta[tag] = True
                    meta["retry_after_http"] = exc.code
                    return data, meta
                except urllib.error.HTTPError as retry_http:
                    last_detail = retry_http.read().decode("utf-8", errors="ignore")[:600]
                except Exception as retry_exc:  # noqa: BLE001
                    last_detail = str(retry_exc)[:600]

            reason = f"GLM 识图失败：HTTP {exc.code} {last_detail}"
            if self.mode == "glm":
                raise RuntimeError(reason) from exc
            return fallback, {"used": False, "reason": reason, "vision": True}
        except Exception as exc:  # noqa: BLE001
            reason = f"GLM 识图失败：{exc}"
            if self.mode == "glm":
                raise RuntimeError(reason) from exc
            return fallback, {"used": False, "reason": reason, "vision": True}


def _maybe_downscale_image(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """压缩大图但保留长截图文字宽度，避免把清晰长图缩成窄条。"""
    if len(image_bytes) < 1_200_000:
        return image_bytes, mime


def split_image_for_ocr(
    image_bytes: bytes,
    mime: str,
    *,
    tile_height: int = 2400,
    overlap: int = 160,
) -> list[tuple[bytes, str]]:
    """把超长截图切成保持原始宽度的重叠分片；普通截图原样返回。"""
    try:
        from io import BytesIO

        from PIL import Image  # type: ignore
    except Exception:  # noqa: BLE001
        return [(image_bytes, mime)]
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        if height <= tile_height and width <= 2400:
            return [(image_bytes, mime)]
        # 横向超宽图先按宽度缩到 2000；长图不按高度缩放。
        if width > 2000:
            scale = 2000 / width
            image = image.resize(
                (2000, max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
            width, height = image.size
        step = max(400, tile_height - overlap)
        tiles: list[tuple[bytes, str]] = []
        top = 0
        while top < height:
            bottom = min(height, top + tile_height)
            tile = image.crop((0, top, width, bottom))
            out = BytesIO()
            tile.save(out, format="JPEG", quality=92, optimize=True)
            tiles.append((out.getvalue(), "image/jpeg"))
            if bottom >= height:
                break
            top += step
        return tiles or [(image_bytes, mime)]
    except Exception:  # noqa: BLE001
        return [(image_bytes, mime)]
    try:
        from io import BytesIO

        from PIL import Image  # type: ignore
    except Exception:  # noqa: BLE001
        return image_bytes, mime

    try:
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")
        max_width = 1800
        w, h = img.size
        # 只按宽度限制缩放。招聘 App 长截图高度可能达到数千像素；
        # 若按最长边缩放，会让 1080px 宽文字缩到两三百像素而无法 OCR。
        scale = min(1.0, max_width / max(w, 1))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return image_bytes, mime


llm = LLMClient()
