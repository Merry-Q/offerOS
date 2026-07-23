import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
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
        self.llm_mode = os.getenv("LLM_MODE", "auto").lower()
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
