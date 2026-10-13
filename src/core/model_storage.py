"""Guarded storage operations for active and candidate grouping models."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import joblib

from ..config import DEFAULT_MODEL_PATH, get_settings


def ensure_model_write_allowed(
    target: str | Path,
    *,
    active_model_path: str | Path | None = None,
    approved_promotion: bool = False,
) -> None:
    """Refuse writes to the active model location outside approved promotion."""
    active_path = Path(active_model_path or DEFAULT_MODEL_PATH).resolve()
    target_path = Path(target).resolve()
    targets_active_model = target_path == active_path or target_path == active_path.parent
    if not targets_active_model:
        return
    if not approved_promotion:
        raise PermissionError(
            f"Writing to the active model location '{active_path.parent}' is disabled. "
            "Train to models/candidate/ and use the manual promotion procedure."
        )
    if not get_settings().model_promotion_enabled:
        raise PermissionError(
            "Model promotion is disabled. Set MODEL_PROMOTION_ENABLED=true and "
            "use the explicit manual promotion command with --approve."
        )


def save_model_artifact(model: Any, output_dir: str | Path, filename: str) -> Path:
    """Save a trained model atomically after applying the active-model guard."""
    output_path = Path(output_dir)
    ensure_model_write_allowed(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    destination = output_path / filename
    ensure_model_write_allowed(destination)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=output_path, suffix=".tmp") as temp_file:
            temporary_path = Path(temp_file.name)
        joblib.dump(model, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


def write_model_metadata(path: str | Path, content: dict[str, Any]) -> Path:
    """Atomically write model metadata only outside the active model location."""
    destination = Path(path)
    ensure_model_write_allowed(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            dir=destination.parent,
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
        ) as temp_file:
            temporary_path = Path(temp_file.name)
            json.dump(content, temp_file, indent=2, ensure_ascii=False)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination
