from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://conflict:conflict@localhost:5434/conflict_screening"

    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-4-5"
    LLM_TEMPERATURE: float = 0
    LLM_MAX_TOKENS: int = 4096
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

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
    LOG_LEVEL: str = "INFO"
    GRAPH_RECURSION_LIMIT: int = 25


settings = Settings()
