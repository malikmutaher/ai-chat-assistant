"""
Central configuration, loaded from environment variables (with sane
defaults for local development). Import `settings` anywhere it's needed
rather than reading os.environ directly, so every module agrees on the
same values.
"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is a convenience, not a hard requirement — if it's not
    # installed, we just fall back to whatever is already in the environment.
    pass


@dataclass(frozen=True)
class Settings:
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./shopping_assistant.db")

    # LLM (Ollama)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    # Future hosted-model option (kept unused until you swap in an API key)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Scraping
    SCRAPE_WAIT_SECONDS: int = int(os.getenv("SCRAPE_WAIT_SECONDS", "5"))
    SCRAPE_SCROLL_PASSES: int = int(os.getenv("SCRAPE_SCROLL_PASSES", "2"))
    SCRAPE_MAX_SCROLLS: int = int(os.getenv("SCRAPE_MAX_SCROLLS", "8"))
    SCRAPE_MAX_PAGES: int = int(os.getenv("SCRAPE_MAX_PAGES", "3"))

    # API
    CORS_ALLOW_ORIGINS: tuple = tuple(
        os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
    )


settings = Settings()
