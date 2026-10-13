"""Application configuration for Taxi Grouper."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

MAX_TAXI_CAPACITY = 4
UNKNOWN_ZONE = "UNKNOWN"
TAXI_COLUMN = "Groupe Taxi"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DEFAULT_MODEL_PATH = MODELS_DIR / "taxi_grouping_model.pkl"
DEFAULT_CANDIDATE_MODEL_PATH = MODELS_DIR / "candidate" / DEFAULT_MODEL_PATH.name
DEFAULT_CONFIG_PATH = MODELS_DIR / "config.json"


ZONE_COMPATIBILITY: dict[str, list[str]] = {
    "A": ["B", "E"],
    "B": ["A", "E"],
    "D": ["E"],
    "E": ["A", "B", "D"],
    "F": ["G", "H"],
    "G": ["F", "H"],
    "H": ["F", "G", "I"],
    "I": ["H"],
    "J": ["K"],
    "K": ["J"],
}


@dataclass(frozen=True)
class GrouperConfig:
    max_capacity: int = MAX_TAXI_CAPACITY
    taxi_column: str = TAXI_COLUMN
    model_path: Path = DEFAULT_MODEL_PATH
    day_first: bool = True
    excel_date_serial_min: int = 43831
    excel_date_serial_max: int = 73415


@dataclass(frozen=True)
class Settings:
    google_client_id: str | None = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret: str | None = os.getenv("GOOGLE_CLIENT_SECRET")
    google_api_key: str | None = os.getenv("GOOGLE_API_KEY")
    google_oauth_redirect_uri: str = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    allowed_origins: list[str] = field(default_factory=list)
    # Minimal scopes required: Sheets access plus Drive file access for picker and metadata
    google_scopes: list[str] = field(default_factory=lambda: [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ])
    retrain_threshold: int = int(os.getenv("RETRAIN_THRESHOLD", "20"))
    model_promotion_enabled: bool = False


def get_settings() -> Settings:
    origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
    model_promotion_enabled = os.getenv("MODEL_PROMOTION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return Settings(
        allowed_origins=origins,
        model_promotion_enabled=model_promotion_enabled,
    )
