"""Small environment-backed settings for the API process."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Load root configuration consistently across platforms without overriding
# values explicitly supplied by the process environment.
load_dotenv(PROJECT_ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    title: str = "SentinelP2P API"
    data_dir: Path = Path(os.getenv("SENTINEL_DATA_DIR", PROJECT_ROOT / "data"))
    investigation_db: Path = Path(os.getenv(
        "SENTINEL_INVESTIGATION_DB",
        Path(os.getenv("SENTINEL_DATA_DIR", PROJECT_ROOT / "data")) / "investigations.sqlite3",
    ))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if origin.strip()
    )


settings = Settings()
