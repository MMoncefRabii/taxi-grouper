"""Command line entry point for grouping a new Excel file."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.adapters.exporter import export_like_historique
from src.core.grouper import group_agents, validate_dispatch
from src.core.preprocessing import detect_columns, filter_dataframe, load_dispatch_excel


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
    df = load_dispatch_excel(args.input)
    columns = detect_columns(df)
    df = filter_dataframe(df, columns, args.time, args.type_course, args.operation)
    grouped, warnings = group_agents(df, columns=columns, use_ml=not args.no_ml)
    validation = validate_dispatch(grouped)
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
