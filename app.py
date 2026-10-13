"""Streamlit interface for Taxi Grouper - Grand Tunis."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config import DATA_DIR, OUTPUTS_DIR
from src.adapters.exporter import export_excel
from src.core.grouper import group_agents, validate_groups
from src.core.preprocessing import detect_columns, filter_dataframe


st.set_page_config(page_title="Taxi Grouper - Grand Tunis", layout="wide")
st.title("Taxi Grouper - Grand Tunis")

uploaded = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])
time_value = st.text_input("Time", value="")
type_course = st.selectbox("Type de course", ["", "Ramassage", "Retour"])
operation = st.text_input("Client / Operation", value="")

if uploaded:
    df = pd.read_excel(uploaded)
    try:
        columns = detect_columns(df)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    filtered = filter_dataframe(
        df,
        columns,
        time_value=time_value or None,
        type_course=type_course or None,
        operation=operation or None,
    )

    st.caption(f"{len(filtered)} rows ready for grouping")
    if st.button("Run automatic grouping", type="primary"):
        grouped, warnings = group_agents(filtered, columns=columns, use_ml=True)
        validate_groups(grouped)
        st.session_state["grouped"] = grouped
        st.session_state["warnings"] = warnings

if "grouped" in st.session_state:
    grouped = st.session_state["grouped"]
    for warning in st.session_state.get("warnings", []):
        st.warning(warning)

    st.subheader("Grouped table")
    edited = st.data_editor(grouped, use_container_width=True, num_rows="fixed")
    st.session_state["grouped"] = edited

    unknown = edited[edited["Zone"] == "UNKNOWN"]
    st.subheader("Unknown addresses")
    if unknown.empty:
        st.success("No unknown addresses.")
    else:
        st.dataframe(unknown, use_container_width=True)

    output_name = f"grouped_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path = OUTPUTS_DIR / output_name
    export_excel(edited, output_path)
    st.download_button(
        "Download final Excel",
        data=output_path.read_bytes(),
        file_name=output_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if st.button("Save corrected results for future training"):
        corrected_dir = DATA_DIR / "corrected"
        corrected_dir.mkdir(parents=True, exist_ok=True)
        corrected_path = corrected_dir / f"corrected_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        edited.to_excel(corrected_path, index=False)
        st.success(f"Saved to {corrected_path}")
