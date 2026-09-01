import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        # 去 BOM，避免首行键名变成 \ufeffGLM_API_KEY 导致读不到
        raw = env_path.read_text(encoding="utf-8-sig")
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.glm_api_key = os.getenv("GLM_API_KEY", "").strip()
        self.glm_base_url = os.getenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/")
        self.glm_model = os.getenv("GLM_MODEL", "glm-5.2")
        # 结构化快路径：JD 解析 / 综合判分（目标 3–10s）
        self.glm_fast_model = (
            os.getenv("GLM_FAST_MODEL", "").strip() or "glm-4.7-flash"
        )
        # 行动报告：默认跟主模型；可单独换成更快模型保 SLA
        self.glm_action_model = (
            os.getenv("GLM_ACTION_MODEL", "").strip() or self.glm_model
        )
        # 截图识图用视觉模型；未配置时默认 glm-5v-turbo
        self.glm_vision_model = (
            os.getenv("GLM_VISION_MODEL", "").strip() or "glm-5v-turbo"
        )
        self.llm_mode = os.getenv("LLM_MODE", "auto").lower()
        self.llm_disable_thinking = _env_bool("LLM_DISABLE_THINKING", default=True)
        self.llm_timeout_fast = max(8, int(os.getenv("LLM_TIMEOUT_FAST", "12")))
        self.llm_timeout_action = max(20, int(os.getenv("LLM_TIMEOUT_ACTION", "45")))
        self.llm_timeout_default = max(15, int(os.getenv("LLM_TIMEOUT_DEFAULT", "60")))
        self.offeros_host = os.getenv("OFFEROS_HOST", "127.0.0.1")
        self.offeros_port = int(os.getenv("OFFEROS_PORT", "8000"))
        self.data_dir = ROOT / "data"
        self.upload_dir = ROOT / "data" / "uploads"
        self.db_path = ROOT / "data" / "offeros_v2.db"
        self.auth_secret = os.getenv("AUTH_SECRET", "offeros-dev-secret-change-me").strip()
        self.admin_username = os.getenv("ADMIN_USERNAME", "admin").strip()
        self.admin_password = os.getenv("ADMIN_PASSWORD", "admin123").strip()
        self.environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        # Production defaults to docs off; development keeps docs on unless overridden.
        self.disable_docs = _env_bool(
            "DISABLE_DOCS",
            default=self.environment in {"production", "prod"},
        )
        self.max_upload_mb = max(1, int(os.getenv("MAX_UPLOAD_MB", "5")))
        self.jd_image_max_mb = max(5, int(os.getenv("JD_IMAGE_MAX_MB", "30")))
        self.jina_api_key = os.getenv("JINA_API_KEY", "").strip()
        raw_cors = os.getenv("CORS_ORIGINS", "*").strip()
        self.cors_origins = [o.strip() for o in raw_cors.split(",") if o.strip()] or ["*"]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    @property
    def llm_configured(self) -> bool:
        key = self.glm_api_key.strip()
        if not key:
            return False
        placeholders = {"your_glm_api_key_here", "changeme", "sk-xxx", "replace_me"}
        return key.lower() not in placeholders


settings = Settings()
