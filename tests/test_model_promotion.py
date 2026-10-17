import hashlib
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import src.data.training_data_manager as training_manager
import train


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configure_retraining_pipeline(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    active_path.parent.mkdir(parents=True)
    candidate_path.parent.mkdir(parents=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    candidate_model = object()
    live_model = object()

    monkeypatch.setattr(training_manager, "DEFAULT_MODEL_PATH", active_path)
    monkeypatch.setattr(training_manager, "CANDIDATE_MODEL_DIR", candidate_path.parent)
    monkeypatch.setattr(training_manager, "CANDIDATE_MODEL_PATH", candidate_path)
    monkeypatch.setattr(training_manager, "EVALUATION_REPORT_PATH", tmp_path / "evaluation.json")
    monkeypatch.setattr(training_manager, "count_training_corrections", lambda: 10)
    monkeypatch.setattr(training_manager, "load_retrain_state", lambda: {})
    monkeypatch.setattr(training_manager, "load_corrections_from_jsonl", lambda: [{"correction": 1}])
    monkeypatch.setattr(
        training_manager,
        "corrections_to_training_dataframe",
        lambda _corrections: pd.DataFrame({"Date": ["2026-01-01"]}),
    )
    monkeypatch.setattr(training_manager, "normalize_training_dataframe_for_historique", lambda df: df)
    monkeypatch.setattr(training_manager, "write_training_dataframe_to_excel", lambda _df, _path: None)
    monkeypatch.setattr(
        training_manager,
        "train_model_from_historique_excel",
        lambda _file, _output: {"accuracy": 0.8},
    )
    monkeypatch.setattr(
        training_manager,
        "load_model",
        lambda path: candidate_model if Path(path) == candidate_path else live_model,
    )
    monkeypatch.setattr(training_manager, "build_default_holdout_dataframe", lambda: pd.DataFrame())
    monkeypatch.setattr(
        training_manager,
        "evaluate_historique_model_on_dataframe",
        lambda model, _df: {
            "accuracy": 0.99 if model is candidate_model else 0.5,
            "example_count": 10,
        },
    )
    monkeypatch.setattr(training_manager, "save_retrain_state", lambda _state: None)
    return active_path


def test_retraining_candidate_with_higher_score_never_replaces_active_model(monkeypatch, tmp_path):
    active_path = _configure_retraining_pipeline(monkeypatch, tmp_path)
    before = _sha256(active_path)
    promotion_calls = []
    monkeypatch.setattr(
        training_manager,
        "promote_candidate_model",
        lambda *args, **kwargs: promotion_calls.append((args, kwargs)),
    )

    result = training_manager.run_retraining_pipeline(threshold=1)

    assert result["candidate_accuracy"] > result["live_accuracy"]
    assert promotion_calls == []
    assert _sha256(active_path) == before


def test_background_retraining_trigger_does_not_promote(monkeypatch, tmp_path):
    import src.api.service as service

    active_path = _configure_retraining_pipeline(monkeypatch, tmp_path)
    before = _sha256(active_path)
    promotion_calls = []
    monkeypatch.setattr(
        service,
        "run_retraining_pipeline",
        training_manager.run_retraining_pipeline,
    )
    monkeypatch.setattr(
        training_manager,
        "promote_candidate_model",
        lambda *args, **kwargs: promotion_calls.append((args, kwargs)),
    )

    service._background_retrain(1)

    assert promotion_calls == []
    assert _sha256(active_path) == before


def test_candidate_evaluation_alone_never_replaces_active_model(monkeypatch, tmp_path):
    import stage3_promotion

    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    report_path = tmp_path / "models" / "evaluation_report.json"
    active_path.parent.mkdir()
    candidate_path.parent.mkdir()
    active_path.write_bytes(b"active model")
    before = _sha256(active_path)

    monkeypatch.setattr(stage3_promotion, "LIVE_MODEL_PATH", active_path)
    monkeypatch.setattr(stage3_promotion, "CANDIDATE_MODEL_PATH", candidate_path)
    monkeypatch.setattr(stage3_promotion, "EVALUATION_REPORT_PATH", report_path)
    monkeypatch.setattr(stage3_promotion, "parse_args", lambda: SimpleNamespace(scenario="normal"))
    monkeypatch.setattr(
        stage3_promotion,
        "build_synthetic_historique_set",
        lambda: (
            pd.DataFrame({"Date": ["training"]}),
            pd.DataFrame([{column: column for column in stage3_promotion.HISTORIQUE_HEADER}]),
        ),
    )
    monkeypatch.setattr(stage3_promotion, "write_synthetic_historique_file", lambda _df, _path: None)
    monkeypatch.setattr(
        stage3_promotion,
        "load_historique_excel",
        lambda _path: pd.DataFrame([{column: column for column in stage3_promotion.HISTORIQUE_HEADER}]),
    )

    def train_candidate(_training_file, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(b"candidate model")
        return {"accuracy": 1.0}

    monkeypatch.setattr(stage3_promotion, "train_model_from_historique_excel", train_candidate)
    monkeypatch.setattr(
        stage3_promotion,
        "load_model",
        lambda path: "live" if Path(path) == active_path else "candidate",
    )
    monkeypatch.setattr(
        stage3_promotion,
        "evaluate_historique_model",
        lambda model, _df: {"accuracy": 1.0 if model == "candidate" else 0.0, "example_count": 1},
    )
    monkeypatch.setattr(stage3_promotion, "summarize_holdout_examples", lambda _df, limit: [])

    stage3_promotion.main()

    assert _sha256(active_path) == before


def test_manual_promotion_requires_approval_and_preserves_active_without_it(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    candidate_path.parent.mkdir(parents=True)
    active_path.parent.mkdir(exist_ok=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    before = _sha256(active_path)
    monkeypatch.setenv("MODEL_PROMOTION_ENABLED", "true")

    with pytest.raises(PermissionError, match="approval"):
        training_manager.promote_candidate_model(
            active_path,
            candidate_path,
            approved=False,
            approved_by="operator",
            candidate_version="candidate-v1",
            metrics={"accuracy": 0.9},
        )

    assert _sha256(active_path) == before


def test_manual_promotion_setting_is_off_by_default(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    candidate_path.parent.mkdir(parents=True)
    active_path.parent.mkdir(exist_ok=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    before = _sha256(active_path)
    monkeypatch.delenv("MODEL_PROMOTION_ENABLED", raising=False)

    with pytest.raises(PermissionError, match="disabled"):
        training_manager.promote_candidate_model(
            active_path,
            candidate_path,
            approved=True,
            approved_by="operator",
            candidate_version="candidate-v1",
            metrics={"accuracy": 0.9},
        )

    assert _sha256(active_path) == before


def test_central_model_writer_refuses_active_model_path(monkeypatch, tmp_path):
    from src.core import model_storage

    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    active_path.parent.mkdir()
    active_path.write_bytes(b"active model")
    before = _sha256(active_path)
    monkeypatch.setattr(model_storage, "DEFAULT_MODEL_PATH", active_path)

    with pytest.raises(PermissionError, match="manual promotion"):
        model_storage.save_model_artifact(object(), active_path.parent, active_path.name)

    assert _sha256(active_path) == before


def test_approved_manual_promotion_logs_metrics_and_keeps_rollback_copy(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    candidate_path.parent.mkdir(parents=True)
    active_path.parent.mkdir(exist_ok=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    monkeypatch.setenv("MODEL_PROMOTION_ENABLED", "true")

    training_manager.promote_candidate_model(
        active_path,
        candidate_path,
        approved=True,
        approved_by="operator",
        candidate_version="candidate-v1",
        metrics={"accuracy": 0.9},
    )

    assert active_path.read_bytes() == b"candidate model"
    log_path = active_path.parent / "promotion_log.jsonl"
    logged = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert logged[-1]["approved_by"] == "operator"
    assert logged[-1]["candidate_version"] == "candidate-v1"
    assert logged[-1]["metrics"] == {"accuracy": 0.9}
    assert logged[-1]["timestamp"]
    assert list((active_path.parent / "rollback").glob("*.pkl"))


def test_failed_manual_promotion_leaves_active_model_intact(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    candidate_path.parent.mkdir(parents=True)
    active_path.parent.mkdir(exist_ok=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    before = _sha256(active_path)
    monkeypatch.setenv("MODEL_PROMOTION_ENABLED", "true")
    real_replace = training_manager.os.replace

    def fail_active_replace(source, destination):
        if Path(destination) == active_path:
            raise OSError("simulated interrupted promotion")
        real_replace(source, destination)

    monkeypatch.setattr(training_manager.os, "replace", fail_active_replace)

    with pytest.raises(OSError, match="simulated interrupted"):
        training_manager.promote_candidate_model(
            active_path,
            candidate_path,
            approved=True,
            approved_by="operator",
            candidate_version="candidate-v1",
            metrics={"accuracy": 0.9},
        )

    assert _sha256(active_path) == before


def test_promotion_log_failure_restores_the_previous_active_model(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    candidate_path.parent.mkdir(parents=True)
    active_path.parent.mkdir(exist_ok=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    before = _sha256(active_path)
    monkeypatch.setenv("MODEL_PROMOTION_ENABLED", "true")
    real_replace = training_manager.os.replace
    log_path = active_path.parent / "promotion_log.jsonl"

    def fail_log_replace(source, destination):
        if Path(destination) == log_path:
            raise OSError("simulated promotion log failure")
        real_replace(source, destination)

    monkeypatch.setattr(training_manager.os, "replace", fail_log_replace)

    with pytest.raises(OSError, match="promotion log failure"):
        training_manager.promote_candidate_model(
            active_path,
            candidate_path,
            approved=True,
            approved_by="operator",
            candidate_version="candidate-v1",
            metrics={"accuracy": 0.9},
        )

    assert _sha256(active_path) == before


def test_approved_rollback_restores_the_previous_model(monkeypatch, tmp_path):
    active_path = tmp_path / "models" / "taxi_grouping_model.pkl"
    candidate_path = tmp_path / "models" / "candidate" / active_path.name
    candidate_path.parent.mkdir(parents=True)
    active_path.parent.mkdir(exist_ok=True)
    active_path.write_bytes(b"active model")
    candidate_path.write_bytes(b"candidate model")
    monkeypatch.setenv("MODEL_PROMOTION_ENABLED", "true")

    training_manager.promote_candidate_model(
        active_path,
        candidate_path,
        approved=True,
        approved_by="operator",
        candidate_version="candidate-v1",
        metrics={"accuracy": 0.9},
    )
    restored = training_manager.rollback_active_model(
        active_path,
        approved=True,
        approved_by="operator",
    )

    assert active_path.read_bytes() == b"active model"
    assert restored.read_bytes() == b"active model"


def test_train_cli_default_output_keeps_active_model_unchanged(monkeypatch, tmp_path):
    from src.config import DEFAULT_MODEL_PATH

    active_before = _sha256(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None
    candidate_model_path = tmp_path / "models" / "candidate" / DEFAULT_MODEL_PATH.name
    monkeypatch.setattr(train, "DEFAULT_CANDIDATE_MODEL_PATH", candidate_model_path)
    monkeypatch.setattr(sys, "argv", ["train.py", "--data", "training-data"])

    def train_candidate(_data_dir, output_dir):
        candidate_dir = Path(output_dir)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / DEFAULT_MODEL_PATH.name).write_bytes(b"candidate model")
        return {"accuracy": 0.9, "precision": 0.9, "recall": 0.9, "f1": 0.9}

    monkeypatch.setattr(train, "train_from_folder", train_candidate)
    train.main()

    assert candidate_model_path.read_bytes() == b"candidate model"
    active_after = _sha256(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None
    assert active_after == active_before


def test_train_cli_rejects_explicit_active_directory_without_changing_model(monkeypatch):
    from src.config import DEFAULT_MODEL_PATH

    before = _sha256(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None
    called = []
    monkeypatch.setattr(sys, "argv", ["train.py", "--data", "training-data", "--output", "models"])
    monkeypatch.setattr(train, "train_from_folder", lambda *_args: called.append(True))

    with pytest.raises(SystemExit, match="candidate|promotion"):
        train.main()

    assert called == []
    after = _sha256(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None
    assert after == before


def test_yellow_express_training_writes_candidate_and_keeps_active_model(monkeypatch, tmp_path):
    from src.config import DEFAULT_MODEL_PATH
    from src.core import ml_model

    candidate_model_path = tmp_path / "models" / "candidate" / DEFAULT_MODEL_PATH.name
    monkeypatch.setattr(ml_model, "DEFAULT_CANDIDATE_MODEL_PATH", candidate_model_path)
    source_path = Path(__file__).resolve().parents[1] / "yellow_express_dispatch.py"
    source = source_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    window_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "YellowExpressDispatch"
    )
    training_handler = next(
        node
        for node in window_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_training"
    )
    trainer_call = next(
        node
        for node in ast.walk(training_handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "train_candidate_from_historique_excel"
    )
    assert trainer_call is not None
    before = _sha256(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None

    candidate_outputs = []

    def train_candidate(_file_path, output_dir):
        candidate_dir = Path(output_dir)
        candidate_outputs.append(candidate_dir)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / DEFAULT_MODEL_PATH.name).write_bytes(b"candidate model")
        return {"accuracy": 0.9}

    monkeypatch.setattr(ml_model, "train_model_from_historique_excel", train_candidate)
    ml_model.train_candidate_from_historique_excel("history.xlsx")

    assert candidate_outputs == [candidate_model_path.parent]
    after = _sha256(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None
    assert after == before
