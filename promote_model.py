"""Explicitly approve candidate model promotion or restore a saved model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.config import DEFAULT_CANDIDATE_MODEL_PATH, DEFAULT_MODEL_PATH
from src.data.training_data_manager import promote_candidate_model, rollback_active_model


def _candidate_metrics(candidate_path: Path, metrics_path: str | None) -> dict[str, Any]:
    path = Path(metrics_path) if metrics_path else candidate_path.parent / "training_report.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Candidate metrics not found: {path}. Provide --metrics-json with an evaluation report."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Candidate metrics JSON must contain an object.")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manually approve model promotion or rollback.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    promote = subparsers.add_parser("promote", help="Promote a candidate after human review.")
    promote.add_argument("--approve", action="store_true", required=True, help="Confirm human approval.")
    promote.add_argument("--approved-by", required=True, help="Name or identifier of the approving person.")
    promote.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE_MODEL_PATH)
    promote.add_argument("--candidate-version")
    promote.add_argument("--metrics-json", help="JSON metrics file; defaults to candidate/training_report.json.")

    rollback = subparsers.add_parser("rollback", help="Restore the most recent saved active model.")
    rollback.add_argument("--approve", action="store_true", required=True, help="Confirm human approval.")
    rollback.add_argument("--approved-by", required=True, help="Name or identifier of the approving person.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "promote":
        metrics = _candidate_metrics(args.candidate, args.metrics_json)
        promote_candidate_model(
            DEFAULT_MODEL_PATH,
            args.candidate,
            approved=args.approve,
            approved_by=args.approved_by,
            candidate_version=args.candidate_version,
            metrics=metrics,
        )
        print(f"Promoted {args.candidate} to {DEFAULT_MODEL_PATH}.")
        return
    restored = rollback_active_model(
        DEFAULT_MODEL_PATH,
        approved=args.approve,
        approved_by=args.approved_by,
    )
    print(f"Restored active model from {restored}.")


if __name__ == "__main__":
    main()
