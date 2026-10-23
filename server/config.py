import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        # 去 BOM，避免首行键名变成 \ufeffDASHSCOPE_API_KEY 导致读不到
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
        self.dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.dashscope_base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
        self.dashscope_generation_url = os.getenv("DASHSCOPE_GENERATION_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation").strip()
        self.qwen_model = os.getenv("QWEN_MODEL", "qwen-plus").strip()
        self.qwen_fast_model = os.getenv("QWEN_FAST_MODEL", "qwen-flash").strip()
        self.qwen_search_model = os.getenv("QWEN_SEARCH_MODEL", "qwen-plus").strip()
        self.qwen_action_model = os.getenv("QWEN_ACTION_MODEL", "qwen-plus").strip()
        self.discovery_limit = min(60, max(3, int(os.getenv("DISCOVERY_LIMIT", "24"))))
        self.discovery_search_rounds = min(6, max(1, int(os.getenv("DISCOVERY_SEARCH_ROUNDS", "6"))))
        self.discovery_candidate_limit = min(160, max(self.discovery_limit, int(os.getenv("DISCOVERY_CANDIDATE_LIMIT", "96"))))
        self.discovery_verify_workers = min(6, max(1, int(os.getenv("DISCOVERY_VERIFY_WORKERS", "4"))))
        self.llm_mode = "mock" if os.getenv("LLM_MODE", "auto").lower() == "mock" else "auto"
        self.llm_timeout_fast = max(8, int(os.getenv("LLM_TIMEOUT_FAST", "12")))
        self.llm_timeout_action = max(20, int(os.getenv("LLM_TIMEOUT_ACTION", "45")))
        self.llm_timeout_default = max(15, int(os.getenv("LLM_TIMEOUT_DEFAULT", "60")))
        raw_base = os.getenv("OFFEROS_BASE_PATH", "").strip()
        if raw_base in {"", "/"}:
            self.public_base_path = ""
        else:
            if not raw_base.startswith("/"):
                raw_base = "/" + raw_base
            self.public_base_path = raw_base.rstrip("/")
        self.data_dir = Path(os.getenv("OFFEROS_DATA_DIR") or ROOT / "data")
        self.upload_dir = self.data_dir / "uploads"
        self.db_path = self.data_dir / "offeros_v2.db"
        self.admin_username = os.getenv("ADMIN_USERNAME", "admin").strip()
        self.admin_password = os.getenv("ADMIN_PASSWORD", "admin123").strip()
        self.environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        if self.environment in {"production", "prod"} and (
            len(self.admin_password) < 12 or self.admin_password == "change-me-strong-password"
        ):
            raise ValueError("生产环境必须配置至少12位的独立 ADMIN_PASSWORD，不能使用示例口令。")
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
        key = self.dashscope_api_key.strip()
        if not key:
            return False
        placeholders = {"your_dashscope_api_key_here", "changeme", "sk-xxx", "replace_me"}
        return key.lower() not in placeholders


settings = Settings()
