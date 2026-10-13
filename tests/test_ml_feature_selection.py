import json
import tempfile
from pathlib import Path

import joblib
import pandas as pd

from src.core.ml_model import score_pair, load_model
from src.core.preprocessing import ColumnMap


class DummyModel:
    def __init__(self, feature_names):
        # feature_names: list of feature column names saved with the model
        self._feature_names = feature_names

    def predict_proba(self, x):
        # Assert that the incoming x has the expected number of features
        assert x.shape[1] == len(self._feature_names)
        # return probability that second class is 0.9
        return [[0.1, 0.9]]


def make_row() -> pd.Series:
    return pd.Series({
        "Date": "2026-07-01",
        "Adresse": "Ariana",
        "Opération": "OP",
        "Site": "S1",
        "Heure d'arrivée": "07:00",
        "BlockID": "Sheet1_0",
    })


def test_score_pair_selects_historique_features():
    # When model declares HISTORIQUE_FEATURE_NAMES, the historique extractor must be used
    from src.core.ml_model import HISTORIQUE_FEATURE_NAMES

    model = DummyModel(HISTORIQUE_FEATURE_NAMES)
    row_a = make_row()
    row_b = make_row()
    cols = ColumnMap(address="Adresse", time="Heure d'arrivée")
    prob = score_pair(model, row_a, row_b, cols)
    assert prob == 0.9


def test_score_pair_selects_pair_features():
    # When model declares regular FEATURE_NAMES, the pair_features extractor must be used
    from src.core.ml_model import FEATURE_NAMES

    model = DummyModel(FEATURE_NAMES)
    row_a = make_row()
    row_b = make_row()
    cols = ColumnMap(address="Adresse", time="Heure d'arrivée")
    prob = score_pair(model, row_a, row_b, cols)
    assert prob == 0.9


def test_load_model_prefers_matching_feature_metadata():
    from src.core.ml_model import HISTORIQUE_FEATURE_NAMES

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        model_file = temp_path / "taxi_grouping_model.pkl"
        config_file = temp_path / "config.json"
        training_file = temp_path / "training_report.json"

        dummy = DummyModel(HISTORIQUE_FEATURE_NAMES)
        dummy.n_features_in_ = len(HISTORIQUE_FEATURE_NAMES)
        joblib.dump(dummy, model_file)

        # config.json contains the wrong feature set length for this model
        wrong_features = ["same_zone"] * (len(HISTORIQUE_FEATURE_NAMES) + 1)
        config_file.write_text(json.dumps({"features": wrong_features}, indent=2), encoding="utf-8")

        # training_report.json contains the correct historique feature set
        training_file.write_text(
            json.dumps({"features": HISTORIQUE_FEATURE_NAMES, "model": "RandomForestClassifier"}, indent=2),
            encoding="utf-8",
        )

        loaded_model = load_model(model_file)
        assert loaded_model is not None
        assert getattr(loaded_model, "_feature_names") == HISTORIQUE_FEATURE_NAMES


def test_load_model_raises_on_conflicting_metadata_lengths():
    from src.core.ml_model import HISTORIQUE_FEATURE_NAMES

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        model_file = temp_path / "taxi_grouping_model.pkl"
        config_file = temp_path / "config.json"
        training_file = temp_path / "training_report.json"

        dummy = DummyModel(HISTORIQUE_FEATURE_NAMES)
        dummy.n_features_in_ = len(HISTORIQUE_FEATURE_NAMES)
        joblib.dump(dummy, model_file)

        # Both metadata files disagree with the estimator's actual feature count
        config_file.write_text(json.dumps({"features": ["same_zone"] * 14}, indent=2), encoding="utf-8")
        training_file.write_text(json.dumps({"features": ["same_zone"] * 12}, indent=2), encoding="utf-8")

        try:
            load_model(model_file)
            assert False, "Expected load_model to raise ValueError when metadata lengths conflict with model.n_features_in_"
        except ValueError as exc:
            assert "No metadata sources match model.n_features_in_" in str(exc)
