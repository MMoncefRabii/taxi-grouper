"""Application configuration for Taxi Grouper."""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

MAX_TAXI_CAPACITY = 4
UNKNOWN_ZONE = "UNKNOWN"
TAXI_COLUMN = "Groupe Taxi"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str | None, default: Path, relative_to: Path) -> Path:
    if value is None:
        return default.resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = relative_to / path
    return path.resolve()


_configured_state_dir = os.getenv("TAXI_GROUPER_STATE_DIR") or None
STATE_DIR = _resolve_path(_configured_state_dir, PROJECT_ROOT, PROJECT_ROOT)
DATA_DIR = _resolve_path(
    os.getenv("TAXI_GROUPER_DATA_DIR") or None,
    STATE_DIR / "data",
    STATE_DIR,
)
MODELS_DIR = _resolve_path(
    os.getenv("TAXI_GROUPER_MODELS_DIR") or None,
    STATE_DIR / "models",
    STATE_DIR,
)
OUTPUTS_DIR = (STATE_DIR / "outputs").resolve()
_default_token_path = (
    DATA_DIR / "google_oauth_tokens.json"
    if _configured_state_dir is not None
    else PROJECT_ROOT / "src" / "data" / "google_oauth_tokens.json"
)
TOKEN_PATH = _resolve_path(
    os.getenv("TAXI_GROUPER_TOKEN_PATH") or None,
    _default_token_path,
    STATE_DIR,
)
DEFAULT_MODEL_PATH = MODELS_DIR / "taxi_grouping_model.pkl"
DEFAULT_CANDIDATE_MODEL_PATH = MODELS_DIR / "candidate" / DEFAULT_MODEL_PATH.name
DEFAULT_CONFIG_PATH = MODELS_DIR / "config.json"
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
logger = logging.getLogger(__name__)


def is_directory_writable(directory: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=directory):
            pass
    except OSError:
        return False
    return True


def _create_state_directory(directory: Path, name: str) -> None:
    existed = directory.exists()
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt" and not existed:
            directory.chmod(0o700)
    except OSError:
        logger.error("State initialization failed: %s", name)
        raise
    if not is_directory_writable(directory):
        logger.error("State initialization failed: %s", name)
        raise PermissionError(f"{name} is not writable.")


def secure_token_file_permissions() -> None:
    if not TOKEN_PATH.exists():
        return
    if os.name == "nt":
        logger.warning("Windows token-file permissions must be set by the operator.")
        return
    TOKEN_PATH.chmod(0o600)


def _warn_if_token_file_permissions_are_insecure() -> None:
    if not TOKEN_PATH.exists():
        return
    if os.name == "nt":
        logger.warning("Windows token-file permissions must be set by the operator.")
        return
    if stat.S_IMODE(TOKEN_PATH.stat().st_mode) & 0o077:
        logger.warning("Token file is group or world readable.")


def ensure_state_directories() -> None:
    directories = (
        (STATE_DIR, "state_directory"),
        (DATA_DIR, "data_directory"),
        (MODELS_DIR, "models_directory"),
        (OUTPUTS_DIR, "outputs_directory"),
        (TOKEN_PATH.parent, "token_directory"),
    )
    checked: set[Path] = set()
    for directory, name in directories:
        if directory not in checked:
            _create_state_directory(directory, name)
            checked.add(directory)
    _warn_if_token_file_permissions_are_insecure()


def _configured_max_upload_size_bytes() -> int:
    raw_value = os.getenv("MAX_UPLOAD_SIZE_BYTES", str(DEFAULT_MAX_UPLOAD_SIZE_BYTES))
    try:
        max_size = int(raw_value)
    except ValueError as exc:
        raise ValueError("MAX_UPLOAD_SIZE_BYTES must be a positive integer.") from exc
    if max_size <= 0:
        raise ValueError("MAX_UPLOAD_SIZE_BYTES must be a positive integer.")
    return max_size


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
    google_output_folder_id: str | None = os.getenv("GOOGLE_OUTPUT_FOLDER_ID")
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
    max_upload_size_bytes: int = field(default_factory=_configured_max_upload_size_bytes)


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
        max_upload_size_bytes=_configured_max_upload_size_bytes(),
    )
