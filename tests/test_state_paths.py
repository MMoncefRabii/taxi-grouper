import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_isolated_python(code: str, working_dir: Path, extra_env: dict[str, str]) -> None:
    env = os.environ.copy()
    for name in (
        "TAXI_GROUPER_STATE_DIR",
        "TAXI_GROUPER_DATA_DIR",
        "TAXI_GROUPER_MODELS_DIR",
        "TAXI_GROUPER_TOKEN_PATH",
    ):
        env.pop(name, None)
    env.update(extra_env)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHON_DOTENV_DISABLED"] = "1"
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=working_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_default_state_paths_preserve_legacy_locations(tmp_path):
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    code = """
import os
from pathlib import Path
from src.config import DATA_DIR, MODELS_DIR, OUTPUTS_DIR, PROJECT_ROOT, STATE_DIR, TOKEN_PATH
root = Path(os.environ["EXPECTED_PROJECT_ROOT"])
assert PROJECT_ROOT == root
assert STATE_DIR == root
assert DATA_DIR == root / "data"
assert MODELS_DIR == root / "models"
assert OUTPUTS_DIR == root / "outputs"
assert TOKEN_PATH == root / "src" / "data" / "google_oauth_tokens.json"
"""
    _run_isolated_python(
        code,
        working_dir,
        {"EXPECTED_PROJECT_ROOT": str(PROJECT_ROOT)},
    )
    assert not list(working_dir.iterdir())


def test_state_directory_redirects_correction_token_and_model_paths(tmp_path):
    state_dir = tmp_path / "external-state"
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    code = """
import os
from pathlib import Path
from src.config import (
    DATA_DIR,
    DEFAULT_CANDIDATE_MODEL_PATH,
    DEFAULT_MODEL_PATH,
    MODELS_DIR,
    OUTPUTS_DIR,
    STATE_DIR,
    TOKEN_PATH,
)
from src.core.model_storage import save_model_artifact
from src.data.sheets_repository import _save_storage
from src.data.training_data_manager import AUTO_TRAINING_JSONL_PATH, write_training_examples_to_file
from fastapi.testclient import TestClient
from src.api.service import app

root = Path(os.environ["EXPECTED_STATE_DIR"]).resolve()
with TestClient(app):
    pass
assert STATE_DIR.is_dir()
assert DATA_DIR.is_dir()
assert MODELS_DIR.is_dir()
assert OUTPUTS_DIR.is_dir()
correction_path = write_training_examples_to_file([{"row_data": {"Adresse": "test"}}])
_save_storage({"current_user": "default", "users": {}})
model_path = save_model_artifact(
    {"test-model": True},
    DEFAULT_CANDIDATE_MODEL_PATH.parent,
    DEFAULT_MODEL_PATH.name,
)
for path in (
    STATE_DIR,
    DATA_DIR,
    MODELS_DIR,
    OUTPUTS_DIR,
    TOKEN_PATH,
    correction_path,
    AUTO_TRAINING_JSONL_PATH,
    DEFAULT_MODEL_PATH,
    DEFAULT_CANDIDATE_MODEL_PATH,
    model_path,
):
    path.resolve().relative_to(root)
assert correction_path == root / "data" / "auto_training_corrections.jsonl"
assert TOKEN_PATH == root / "data" / "google_oauth_tokens.json"
assert model_path == root / "models" / "candidate" / DEFAULT_MODEL_PATH.name
assert correction_path.is_file()
assert TOKEN_PATH.is_file()
assert model_path.is_file()
"""
    _run_isolated_python(
        code,
        working_dir,
        {
            "EXPECTED_STATE_DIR": str(state_dir),
            "TAXI_GROUPER_STATE_DIR": str(state_dir),
        },
    )
    assert not list(working_dir.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not available on Windows")
def test_created_state_directories_and_token_are_private(tmp_path, monkeypatch):
    import src.config as config
    import src.data.sheets_repository as sheets_repository

    state_dir = tmp_path / "private-state"
    data_dir = state_dir / "data"
    models_dir = state_dir / "models"
    outputs_dir = state_dir / "outputs"
    token_path = data_dir / "google_oauth_tokens.json"
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "MODELS_DIR", models_dir)
    monkeypatch.setattr(config, "OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(config, "TOKEN_PATH", token_path)
    monkeypatch.setattr(sheets_repository, "TOKEN_FILE", token_path)

    config.ensure_state_directories()
    sheets_repository._save_storage({"current_user": "default", "users": {}})

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
