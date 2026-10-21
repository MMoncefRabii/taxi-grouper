"""Shared dispatch preparation, grouping, and validation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import BinaryIO, Mapping

import pandas as pd

from src.config import MAX_TAXI_CAPACITY, TAXI_COLUMN
from .grouper import group_agents, validate_dispatch
from .preprocessing import ColumnMap, detect_columns, filter_dataframe, load_dispatch_excel


DispatchSource = str | PathLike[str] | BinaryIO | pd.DataFrame


@dataclass(frozen=True)
class DispatchPipelineResult:
    grouped: pd.DataFrame
    validation: dict
    columns: ColumnMap
    warnings: list[str]
    filtered_count: int


def run_dispatch_pipeline(
    source: DispatchSource,
    *,
    filters: Mapping[str, str | None] | None = None,
    column_overrides: Mapping[str, str] | None = None,
    use_ml: bool = True,
    source_id: str | None = None,
    validation_taxi_column: str = TAXI_COLUMN,
    validation_capacity: int = MAX_TAXI_CAPACITY,
) -> DispatchPipelineResult:
    """Run shared dispatch processing for workbook and Sheets-reader sources.

    Workbook inputs use ``load_dispatch_excel`` (including all-sheet loading,
    repeated-header handling, and dispatch-block metadata). A DataFrame from the
    Sheets reader is kept as-is: its existing reader contract and metadata are
    preserved, while column detection, filtering, grouping, and validation are
    shared with workbook inputs.
    """
    if isinstance(source, pd.DataFrame):
        frame = source.copy()
    else:
        frame = load_dispatch_excel(source, source_id=source_id)

    columns = detect_columns(frame, column_overrides=column_overrides)

    selected_filters = filters or {}
    filtered = filter_dataframe(
        frame,
        columns,
        time_value=selected_filters.get("time_value"),
        type_course=selected_filters.get("type_course"),
        operation=selected_filters.get("operation"),
    )
    grouped, warnings = group_agents(filtered, columns=columns, use_ml=use_ml)
    validation = validate_dispatch(
        grouped,
        taxi_column=validation_taxi_column,
        capacity=validation_capacity,
    )
    return DispatchPipelineResult(
        grouped=grouped,
        validation=validation,
        columns=columns,
        warnings=warnings,
        filtered_count=len(filtered),
    )
