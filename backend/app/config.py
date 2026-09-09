from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://conflict:conflict@localhost:5434/conflict_screening"

    # OpenAI-compatible inference. Points at a local llama.cpp server by
    # default; set LLM_BASE_URL/LLM_API_KEY to use a hosted provider instead.
    LLM_PROVIDER: str = "openai"
    LLM_BASE_URL: str = "http://localhost:8080/v1"
    LLM_MODEL: str = "Qwen3.5-4B"
    LLM_API_KEY: str = "sk-no-key-required"
    LLM_TEMPERATURE: float = 0
    LLM_MAX_TOKENS: int = 1200
    LLM_TIMEOUT_SECONDS: float = 240.0
    # Small local models are slow (~6s/call). Cap judgment calls so a
    # screening stays inside the 90-second budget (DEV_B B16).
    LLM_MAX_ENTITY_ADJUDICATIONS: int = 5
    LLM_ENABLED: bool = True

    MATCH_THRESHOLD_AUTO_INCLUDE: float = 0.80
    MATCH_THRESHOLD_REVIEW: float = 0.65
    PGTRGM_PREFILTER_THRESHOLD: float = 0.30

    COT_CUTOFF_DATE: date = date(2025, 7, 15)
    DCCS_STALENESS_YEARS: int = 2
    WBS_RECENT_COMPLETION_DAYS: int = 180

    XLSX_PATH: str = "../sample_dataset/Sample 3.3 - 12246557 - Compiled Databases (1).xlsx"
    PDF_PATH: str = "../sample_dataset/Sample 3.1 - 12246557 (1).pdf"
    PPTX_PATH: str = "../reference/Quick Reference Card - SEA T&T.pptx"

    DATA_DIR: str = "./data"
    PDFTOTEXT_BIN: str = "pdftotext"
    CORS_ORIGINS: str = "http://localhost:5173"
    # Private-network origins, so the app can be opened from another device on
    # the same LAN. Deliberately scoped to RFC1918 ranges plus localhost.
    CORS_ORIGIN_REGEX: str = (
        r"http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|"
        r"192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?"
    )
    LOG_LEVEL: str = "INFO"
    GRAPH_RECURSION_LIMIT: int = 25


settings = Settings()
