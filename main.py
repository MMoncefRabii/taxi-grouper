"""Command line entry point for grouping a new Excel file."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.adapters.exporter import export_like_historique
from src.core.pipeline import run_dispatch_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Group Grand Tunis agents into taxis.")
    parser.add_argument("--input", required=True, help="Input Excel file")
    parser.add_argument("--output", required=True, help="Output Excel file")
    parser.add_argument("--time", default=None, help="Optional time filter, for example 07:00")
    parser.add_argument("--type-course", default=None, help="Optional course type filter: Ramassage or Retour")
    parser.add_argument("--operation", default=None, help="Optional client/operation filter")
    parser.add_argument("--no-ml", action="store_true", help="Disable ML-assisted ordering")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_dispatch_pipeline(
        args.input,
        filters={
            "time_value": args.time,
            "type_course": args.type_course,
            "operation": args.operation,
        },
        use_ml=not args.no_ml,
    )
    grouped = result.grouped
    warnings = result.warnings
    validation = result.validation
    if validation["errors"]:
        raise ValueError("\n".join(validation["errors"]))
    output = export_like_historique(
        grouped,
        str(Path(args.output)),
        validation_report_path=str(Path(args.output).with_name(f"{Path(args.output).stem}_validation_report.xlsx")),
    )
    for warning in warnings:
        print(warning)
    for warning in validation["warnings"]:
        print(warning)
    print(f"Grouped {len(grouped)} agents into {grouped['Groupe Taxi'].nunique()} taxis.")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
