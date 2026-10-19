import pandas as pd

from src.data import sheets_repository, training_data_manager


class _Request:
    def __init__(self, response):
        self.response = response

    def execute(self):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _Values:
    def __init__(self, values):
        self.values = values

    def get(self, *, spreadsheetId, range):
        assert spreadsheetId == "test-sheet"
        assert range == "'Client'"
        return _Request({"values": self.values})


class _Spreadsheets:
    def __init__(self, merges, fail_merge_request=False, values=None):
        self.merges = merges
        self.fail_merge_request = fail_merge_request
        self._values = values or [
            ["Adresse", "Groupe Taxi"],
            ["address-1", "A"],
            ["address-2"],
            ["address-3"],
            ["address-4"],
        ]

    def get(self, *, spreadsheetId, fields):
        assert spreadsheetId == "test-sheet"
        assert fields in {
            "sheets(properties(sheetId,title),merges)",
            "sheets(properties(sheetId,title))",
        }
        if "merges" in fields and self.fail_merge_request:
            return _Request(RuntimeError("merge metadata request failed"))
        sheet = {"properties": {"sheetId": 17, "title": "Client"}}
        if "merges" in fields:
            sheet["merges"] = self.merges
        return _Request({"sheets": [sheet]})

    def values(self):
        return _Values(self._values)


class _SheetsService:
    def __init__(self, merges, fail_merge_request=False, values=None):
        self._spreadsheets = _Spreadsheets(merges, fail_merge_request, values)

    def spreadsheets(self):
        return self._spreadsheets


def _read_sheet(monkeypatch, merges, *, fail_merge_request=False, values=None):
    service = _SheetsService(merges, fail_merge_request, values)
    monkeypatch.setattr(sheets_repository, "build_sheets_service", lambda: service)
    return sheets_repository._read_google_sheet_to_dataframe("test-sheet", "Client")


def _store_pre_state(monkeypatch, tmp_path, rows):
    monkeypatch.setattr(
        training_data_manager,
        "PRE_CORRECTION_CACHE_DIR",
        tmp_path / "pre-correction",
    )
    training_data_manager.store_pre_correction_state(
        "test-sheet",
        pd.DataFrame(rows, columns=["Adresse", "Groupe Taxi"]),
    )


def test_merged_group_labels_are_filled_before_correction_extraction(monkeypatch, tmp_path):
    post_df = _read_sheet(
        monkeypatch,
        [{"startRowIndex": 1, "endRowIndex": 5, "startColumnIndex": 1, "endColumnIndex": 2}],
    )
    _store_pre_state(
        monkeypatch,
        tmp_path,
        [
            ["address-1", "A"],
            ["address-2", "A"],
            ["address-3", "A"],
            ["address-4", "A"],
        ],
    )

    result = training_data_manager.extract_training_examples_from_corrections(
        "test-sheet", post_df
    )

    assert post_df["Groupe Taxi"].tolist() == ["A", "A", "A", "A"]
    assert result["corrections"] == []


def test_one_genuine_group_move_is_captured_once(monkeypatch, tmp_path):
    post_df = _read_sheet(
        monkeypatch,
        [{"startRowIndex": 1, "endRowIndex": 3, "startColumnIndex": 1, "endColumnIndex": 2}],
        values=[
            ["Adresse", "Groupe Taxi"],
            ["address-1", "A"],
            ["address-2"],
            ["address-3", "B"],
            ["address-4", "A"],
        ],
    )
    _store_pre_state(
        monkeypatch,
        tmp_path,
        [
            ["address-1", "A"],
            ["address-2", "A"],
            ["address-3", "A"],
            ["address-4", "A"],
        ],
    )

    result = training_data_manager.extract_training_examples_from_corrections(
        "test-sheet", post_df
    )

    assert len(result["corrections"]) == 1
    assert result["corrections"][0]["after"] == "B"


def test_unavailable_merge_metadata_skips_correction_capture(monkeypatch, tmp_path):
    post_df = _read_sheet(monkeypatch, [], fail_merge_request=True)
    _store_pre_state(
        monkeypatch,
        tmp_path,
        [
            ["address-1", "A"],
            ["address-2", "A"],
            ["address-3", "A"],
            ["address-4", "A"],
        ],
    )

    result = training_data_manager.extract_training_examples_from_corrections(
        "test-sheet", post_df
    )

    assert result["success"] is False
    assert result["corrections"] == []
    assert result["stats"]["status"] == "merge_info_unavailable"


def test_sanity_limit_rejects_more_than_half_of_rows(monkeypatch, tmp_path):
    _store_pre_state(
        monkeypatch,
        tmp_path,
        [
            ["address-1", "A"],
            ["address-2", "A"],
            ["address-3", "A"],
            ["address-4", "A"],
        ],
    )
    post_df = pd.DataFrame(
        {
            "Adresse": ["address-1", "address-2", "address-3", "address-4"],
            "Groupe Taxi": ["B", "C", "D", "A"],
        }
    )

    result = training_data_manager.extract_training_examples_from_corrections(
        "test-sheet", post_df
    )

    assert result["corrections"] == []
    assert result["status"] == "sanity_limit_exceeded"
    assert result["stats"]["detected_corrections"] == 3


def test_unmerged_blank_taxi_cell_is_not_captured(monkeypatch, tmp_path):
    post_df = _read_sheet(
        monkeypatch,
        [{"startRowIndex": 1, "endRowIndex": 4, "startColumnIndex": 1, "endColumnIndex": 2}],
    )
    _store_pre_state(
        monkeypatch,
        tmp_path,
        [
            ["address-1", "A"],
            ["address-2", "A"],
            ["address-3", "A"],
            ["address-4", "A"],
        ],
    )

    result = training_data_manager.extract_training_examples_from_corrections(
        "test-sheet", post_df
    )

    assert post_df["Groupe Taxi"].tolist() == ["A", "A", "A", ""]
    assert result["corrections"] == []
