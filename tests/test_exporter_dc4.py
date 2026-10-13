import pandas as pd

from src.adapters.exporter import _drop_empty_export_rows


def test_drop_empty_export_rows_removes_blank_rows():
    df = pd.DataFrame(
        [
            {"Date": "2026-07-01", "Nom - Prénom": "A", "Adresse": "Ariana"},
            {"Date": "", "Nom - Prénom": "", "Adresse": ""},
            {"Date": "2026-07-02", "Nom - Prénom": "B", "Adresse": "Ghazela"},
        ]
    )
    out = _drop_empty_export_rows(df)
    assert len(out) == 2
    assert out.iloc[0]["Nom - Prénom"] == "A"
    assert out.iloc[1]["Nom - Prénom"] == "B"
