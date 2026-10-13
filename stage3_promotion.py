"""Stage 3 model evaluation and candidate promotion gate.

This script builds a small human-readable synthetic held-out dataset, trains
an independent candidate historical model on a separate synthetic historical
training file, evaluates both the live model and the candidate on the held-out
pairs, and writes the final decision into models/evaluation_report.json.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score

from src.core.ml_model import (  # type: ignore[attr-defined]
    load_historique_excel,
    load_model,
    prepare_historique_pairwise_examples,
    train_model_from_historique_excel,
)

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models"
CANDIDATE_DIR = MODEL_DIR / "candidate"
EVALUATION_REPORT_PATH = MODEL_DIR / "evaluation_report.json"
LIVE_MODEL_PATH = MODEL_DIR / "taxi_grouping_model.pkl"
CANDIDATE_MODEL_PATH = CANDIDATE_DIR / "taxi_grouping_model.pkl"
HISTORIQUE_HEADER = [
    "Date",
    "Matricule",
    "Nom - Prénom",
    "Opération",
    "Site",
    "Adresse",
    "Heure d'arrivée",
    "Taxi",
]


def build_synthetic_historique_set() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (training_df, heldout_df) in a historical Excel-friendly format."""

    def block_rows(block_id: str, date: str, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        rows.append({col: col for col in HISTORIQUE_HEADER})
        for taxi_label, group in enumerate(groups, start=1):
            for person_id, member in enumerate(group["members"], start=1):
                rows.append(
                    {
                        "Date": date,
                        "Matricule": f"M{block_id}{taxi_label}{person_id}",
                        "Nom - Prénom": member["name"],
                        "Opération": member["operation"],
                        "Site": member["site"],
                        "Adresse": member["address"],
                        "Heure d'arrivée": member["time"],
                        "Taxi": str(group["taxi"]),
                    }
                )
        return rows

    training_blocks = [
        {
            "block_id": "A",
            "date": "2026-07-11",
            "groups": [
                {
                    "taxi": "1",
                    "members": [
                        {
                            "name": "Amine Ben Youssef",
                            "operation": "Site client",
                            "site": "Lafayette",
                            "address": "Rue de Madrid, Tunis",
                            "time": "08:30",
                        },
                        {
                            "name": "Sofia Hachemi",
                            "operation": "Site client",
                            "site": "Lafayette",
                            "address": "Avenue de France, Centre Ville",
                            "time": "08:30",
                        },
                    ],
                },
                {
                    "taxi": "2",
                    "members": [
                        {
                            "name": "Firas Khelifi",
                            "operation": "Dépose gares",
                            "site": "Ghazela",
                            "address": "Ghazela, Ariana",
                            "time": "08:30",
                        },
                        {
                            "name": "Lina Mansour",
                            "operation": "Dépose gares",
                            "site": "Jaafer",
                            "address": "Jaafer, Ghazela",
                            "time": "08:30",
                        },
                    ],
                },
                {
                    "taxi": "3",
                    "members": [
                        {
                            "name": "Nadia Bouazizi",
                            "operation": "Retour hôtel",
                            "site": "Ettadhamen",
                            "address": "Ettadhamen, Tunis",
                            "time": "08:30",
                        },
                        {
                            "name": "Hedi Mansri",
                            "operation": "Retour hôtel",
                            "site": "Oued Lil",
                            "address": "Oued Lil, Ettadhamen",
                            "time": "08:30",
                        },
                    ],
                },
            ],
        },
        {
            "block_id": "B",
            "date": "2026-07-11",
            "groups": [
                {
                    "taxi": "1",
                    "members": [
                        {
                            "name": "Meriem Kallel",
                            "operation": "Aéroport",
                            "site": "Marsa",
                            "address": "Marsa, La Marsa",
                            "time": "10:00",
                        },
                        {
                            "name": "Karim Skhiri",
                            "operation": "Aéroport",
                            "site": "Sidi Bou Said",
                            "address": "Sidi Bou Said, Tunis",
                            "time": "10:00",
                        },
                    ],
                },
                {
                    "taxi": "2",
                    "members": [
                        {
                            "name": "Nesrine Gharbi",
                            "operation": "Visite client",
                            "site": "La Goulette",
                            "address": "La Goulette, Tunis",
                            "time": "10:00",
                        },
                        {
                            "name": "Aymen Trabelsi",
                            "operation": "Visite client",
                            "site": "Carthage",
                            "address": "Carthage, La Goulette",
                            "time": "10:00",
                        },
                    ],
                },
                {
                    "taxi": "3",
                    "members": [
                        {
                            "name": "Sawsan Rekik",
                            "operation": "Site client",
                            "site": "Ariana Centre",
                            "address": "Ariana Centre, Ariana",
                            "time": "10:00",
                        },
                        {
                            "name": "Rami Elloumi",
                            "operation": "Site client",
                            "site": "Cité La Gazelle",
                            "address": "Cité La Gazelle, Ariana",
                            "time": "10:00",
                        },
                    ],
                },
            ],
        },
    ]

    heldout_blocks = [
        {
            "block_id": "C",
            "date": "2026-07-12",
            "groups": [
                {
                    "taxi": "1",
                    "members": [
                        {
                            "name": "Zeinab Tlili",
                            "operation": "Site client",
                            "site": "Bab Saadoun",
                            "address": "Bab Saadoun, Tunis",
                            "time": "11:00",
                        },
                        {
                            "name": "Tarek Jaziri",
                            "operation": "Site client",
                            "site": "Bardo",
                            "address": "Bardo, Tunis",
                            "time": "11:00",
                        },
                    ],
                },
                {
                    "taxi": "2",
                    "members": [
                        {
                            "name": "Imen Jebali",
                            "operation": "Visite client",
                            "site": "Omrane",
                            "address": "Omrane, Tunis",
                            "time": "11:00",
                        },
                        {
                            "name": "Sami El Afrit",
                            "operation": "Visite client",
                            "site": "Nasseer",
                            "address": "Nasseer, Ettadhamen",
                            "time": "11:00",
                        },
                    ],
                },
            ],
        },
        {
            "block_id": "D",
            "date": "2026-07-12",
            "groups": [
                {
                    "taxi": "1",
                    "members": [
                        {
                            "name": "Walid Saidi",
                            "operation": "Retour hôtel",
                            "site": "Ariana Centre",
                            "address": "Ariana Centre, Ariana",
                            "time": "12:00",
                        },
                        {
                            "name": "Mouna Fakhfekh",
                            "operation": "Retour hôtel",
                            "site": "Ghazela",
                            "address": "Ghazela, Ariana",
                            "time": "12:00",
                        },
                    ],
                },
                {
                    "taxi": "2",
                    "members": [
                        {
                            "name": "Aicha Marzouk",
                            "operation": "Site client",
                            "site": "Rue de Madrid",
                            "address": "Rue de Madrid, Tunis",
                            "time": "12:00",
                        },
                        {
                            "name": "Noureddine Kefi",
                            "operation": "Site client",
                            "site": "Bab Souika",
                            "address": "Bab Souika, Tunis",
                            "time": "12:00",
                        },
                    ],
                },
            ],
        },
    ]

    training_rows: list[dict[str, Any]] = []
    heldout_rows: list[dict[str, Any]] = []
    for block in training_blocks:
        training_rows.extend(block_rows(block["block_id"], block["date"], block["groups"]))
    for block in heldout_blocks:
        heldout_rows.extend(block_rows(block["block_id"], block["date"], block["groups"]))

    training_df = pd.DataFrame(training_rows)
    heldout_df = pd.DataFrame(heldout_rows)
    return training_df, heldout_df


def write_synthetic_historique_file(df: pd.DataFrame, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(target_path, index=False, sheet_name="Sheet1")


def corrupt_training_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Return a misleading candidate training set by assigning inconsistent taxi labels."""
    bad = df.copy().reset_index(drop=True)
    taxi_pattern = ["1", "2"] * 6
    data_rows = bad[bad["Date"] != "Date"].index.tolist()
    for position, row_index in enumerate(data_rows):
        bad.at[row_index, "Taxi"] = taxi_pattern[position]
    return bad


def evaluate_historique_model(model: Any, df: pd.DataFrame) -> dict[str, Any]:
    x, y = prepare_historique_pairwise_examples(df)
    if x.shape[0] == 0:
        raise ValueError("No valid pairwise examples could be created from the held-out set.")
    predictions = model.predict(x)
    return {
        "example_count": int(len(y)),
        "accuracy": float(accuracy_score(y, predictions)),
    }


def summarize_holdout_examples(df: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    count = 0
    for record in df.to_dict(orient="records"):
        if record["Date"] == "Date":
            continue
        summary.append(
            {
                "Date": record["Date"],
                "Time": record["Heure d'arrivée"],
                "Address": record["Adresse"],
                "Operation": record["Opération"],
                "Site": record["Site"],
                "Taxi": record["Taxi"],
            }
        )
        count += 1
        if count >= limit:
            break
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 3 candidate promotion evaluation")
    parser.add_argument(
        "--scenario",
        choices=["normal", "bad"],
        default="normal",
        help="Choose normal candidate training data or bad/misleading candidate data to force refusal.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario = args.scenario
    if not LIVE_MODEL_PATH.exists():
        raise FileNotFoundError(f"Live model not found at {LIVE_MODEL_PATH}")

    live_model = load_model(LIVE_MODEL_PATH)
    if live_model is None:
        raise RuntimeError(f"Failed to load live model from {LIVE_MODEL_PATH}")

    training_df, heldout_df = build_synthetic_historique_set()
    display_df = heldout_df[heldout_df["Date"] != "Date"]
    print("Held-out dataset examples (synthetic, human-readable):")
    print(display_df[["Date", "Heure d'arrivée", "Adresse", "Opération", "Site", "Taxi"]].to_string(index=False))
    print(f"\nCandidate scenario: {scenario}")
    print("Training a candidate historical model on synthetic data...")

    if scenario == "bad":
        training_df = corrupt_training_labels(training_df)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        training_file_path = temp_dir_path / "synthetic_historique.xlsx"
        heldout_file_path = temp_dir_path / "synthetic_heldout.xlsx"
        write_synthetic_historique_file(training_df, training_file_path)
        write_synthetic_historique_file(heldout_df, heldout_file_path)
        candidate_metrics = train_model_from_historique_excel(str(training_file_path), str(CANDIDATE_DIR))

        cleaned_heldout = load_historique_excel(str(heldout_file_path))

    candidate_model = load_model(CANDIDATE_MODEL_PATH)
    if candidate_model is None:
        raise RuntimeError("Candidate model failed to load after training.")

    live_results = evaluate_historique_model(live_model, cleaned_heldout)
    candidate_results = evaluate_historique_model(candidate_model, cleaned_heldout)

    decision = (
        "promote"
        if candidate_results["accuracy"] >= live_results["accuracy"]
        else "refuse"
    )
    description = (
        "Candidate model is equal or better than live model on the held-out test set."
        if decision == "promote"
        else "Candidate model scored lower than live model on the held-out test set."
    )

    report = {
        "scenario": scenario,
        "live_model_path": str(LIVE_MODEL_PATH),
        "candidate_model_path": str(CANDIDATE_MODEL_PATH),
        "live_accuracy": live_results["accuracy"],
        "candidate_accuracy": candidate_results["accuracy"],
        "holdout_example_count": live_results["example_count"],
        "decision": decision,
        "description": description,
        "promotion_threshold": float(live_results["accuracy"]),
        "candidate_training_metrics": candidate_metrics,
        "heldout_examples_preview": summarize_holdout_examples(heldout_df, limit=6),
    }

    EVALUATION_REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nEvaluation report written to {EVALUATION_REPORT_PATH}")


if __name__ == "__main__":
    main()
