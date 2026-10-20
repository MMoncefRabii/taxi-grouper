from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_day.xlsx"
EXPECTED_PATH = REPO_ROOT / "tests" / "golden" / "expected_groups.json"
API_KEY = "golden-day-test-api-key-with-at-least-32-characters"
AGENT_COLUMN = "Matricule"
TAXI_COLUMN = "Groupe Taxi"


def _expected_partition() -> list[list[str]]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def _canonical_partition(grouped: pd.DataFrame) -> list[list[str]]:
    groups = [
        sorted(group[AGENT_COLUMN].astype(str).tolist())
        for _, group in grouped.groupby(TAXI_COLUMN, sort=False, dropna=False)
    ]
    return sorted(groups, key=lambda group: group[0] if group else "")


def _partition_from_api(records: list[dict]) -> list[list[str]]:
    return _canonical_partition(pd.DataFrame(records))


def _fail_on_partition_difference(actual: list[list[str]], expected: list[list[str]]) -> None:
    actual_groups = {tuple(group) for group in actual}
    expected_groups = {tuple(group) for group in expected}
    changed = len(actual_groups) - len(actual_groups & expected_groups)
    added_count = max(0, len(actual_groups) - len(expected_groups))
    removed_count = max(0, len(expected_groups) - len(actual_groups))
    if actual_groups != expected_groups:
        pytest.fail(
            "partition mismatch: "
            f"groups added={added_count}, removed={removed_count}, changed={changed}"
        )


def _differing_row_count(first: list[list[str]], second: list[list[str]]) -> int:
    def row_to_group(groups: list[list[str]]) -> dict[str, tuple[str, ...]]:
        return {
            agent_id: tuple(group)
            for group in groups
            for agent_id in group
        }

    first_map = row_to_group(first)
    second_map = row_to_group(second)
    return sum(
        first_map.get(agent_id) != second_map.get(agent_id)
        for agent_id in first_map.keys() | second_map.keys()
    )


def _assert_invariants(grouped: pd.DataFrame) -> None:
    row_count = len(grouped)
    assigned = grouped[TAXI_COLUMN].notna() & grouped[TAXI_COLUMN].astype(str).str.strip().ne("")
    group_sizes = grouped.loc[assigned].groupby(TAXI_COLUMN, dropna=False).size()
    validation = _validate(grouped)
    missing_reason_count = 0
    for column in ("GroupReason", "UnassignedReason"):
        if column in grouped:
            reasons = grouped[column].fillna("").astype(str)
            missing_reason_count += int(reasons.str.startswith("MISSING_").sum())

    assert row_count == 110, f"rows in={110}, rows out={row_count}"
    assert int(assigned.sum()) == 110, f"assigned rows={int(assigned.sum())}, input rows=110"
    assert int(group_sizes.sum()) == 110, f"rows across groups={int(group_sizes.sum())}"
    assert len(grouped[AGENT_COLUMN].astype(str).unique()) == 110, "unique anonymized agent IDs=110"
    assert int(group_sizes.max()) <= 4, f"maximum group size={int(group_sizes.max())}"
    assert not validation["errors"], f"validation errors={len(validation['errors'])}"
    assert missing_reason_count == 0, f"MISSING_* reasons={missing_reason_count}"


def _validate(grouped: pd.DataFrame) -> dict:
    from src.core.grouper import validate_dispatch

    return validate_dispatch(grouped)


def _group_fixture(*, config=None) -> pd.DataFrame:
    from src.core.grouper import group_agents
    from src.core.preprocessing import detect_columns, load_dispatch_excel

    dispatch = load_dispatch_excel(FIXTURE_PATH)
    grouped, _warnings = group_agents(
        dispatch,
        columns=detect_columns(dispatch),
        config=config,
        use_ml=False,
    )
    return grouped


def test_standard_loader_invariants_snapshot_and_determinism() -> None:
    expected = _expected_partition()
    first = _group_fixture()
    _assert_invariants(first)
    actual = _canonical_partition(first)
    _fail_on_partition_difference(actual, expected)

    second = _group_fixture()
    repeated = _canonical_partition(second)
    if repeated != actual:
        pytest.fail(
            "same-process determinism failure: "
            f"groups first={len(actual)}, second={len(repeated)}, "
            f"differing rows={_differing_row_count(actual, repeated)}"
        )


def test_api_upload_route_matches_golden_partition(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.service import app

    monkeypatch.setenv("TAXI_GROUPER_API_KEY", API_KEY)
    response = TestClient(app).post(
        "/api/group?use_ml=false",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={
            "file": (
                FIXTURE_PATH.name,
                FIXTURE_PATH.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    if response.status_code != 200:
        pytest.fail(f"API upload status={response.status_code}")

    result = response.json()
    records = result["grouped_data"]
    grouped = pd.DataFrame(records)
    _assert_invariants(grouped)
    _fail_on_partition_difference(_partition_from_api(records), _expected_partition())
    if not result["validation"]["valid"]:
        pytest.fail("API validation result is invalid")
    if result["validation"]["errors"]:
        pytest.fail(f"API validation errors={len(result['validation']['errors'])}")


def test_clean_runtime_paths_need_no_ignored_data_or_model_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.config as config_module
    import src.core.destination_cleaner as cleaner
    import src.core.destination_detector as detector
    from src.config import GrouperConfig

    empty_runtime = tmp_path / "empty-runtime"
    empty_runtime.mkdir()
    aliases_path = empty_runtime / "destination_aliases.json"
    aliases_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_module, "DATA_DIR", empty_runtime)
    monkeypatch.setattr(config_module, "MODELS_DIR", empty_runtime)
    monkeypatch.setattr(cleaner, "ALIASES_PATH", aliases_path)
    monkeypatch.setattr(cleaner, "UNKNOWN_DESTINATIONS_PATH", empty_runtime / "unknown.csv")
    monkeypatch.setattr(detector, "ALIASES_PATH", aliases_path)
    monkeypatch.setattr(
        cleaner,
        "save_unknown_destinations",
        lambda *_args, **_kwargs: pytest.fail("unexpected unknown-address file write"),
    )

    grouped = _group_fixture(config=GrouperConfig(model_path=empty_runtime / "missing-model.pkl"))
    _assert_invariants(grouped)
    _fail_on_partition_difference(_canonical_partition(grouped), _expected_partition())


@pytest.mark.xfail(
    strict=True,
    reason="Streamlit reads with pandas directly and does not synthesize a dispatch ID.",
)
def test_streamlit_direct_load_reproduces_dispatch_id_gap() -> None:
    from src.core.grouper import group_agents
    from src.core.preprocessing import detect_columns, filter_dataframe

    dispatch = pd.read_excel(FIXTURE_PATH)
    columns = detect_columns(dispatch)
    filtered = filter_dataframe(dispatch, columns)
    grouped, _warnings = group_agents(filtered, columns=columns, use_ml=False)
    assigned = grouped[TAXI_COLUMN].notna() & grouped[TAXI_COLUMN].astype(str).str.strip().ne("")
    assert int(assigned.sum()) == 110, f"assigned rows={int(assigned.sum())}, input rows=110"


def _regenerate_expected_groups() -> None:
    grouped = _group_fixture()
    _assert_invariants(grouped)
    partition = _canonical_partition(grouped)
    EXPECTED_PATH.write_text(json.dumps(partition, indent=2) + "\n", encoding="utf-8")
    print(f"Snapshot regenerated: agents={len(grouped)}, groups={len(partition)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--regenerate-expected-groups",
        action="store_true",
        help="explicitly replace tests/golden/expected_groups.json from the fixture",
    )
    args = parser.parse_args()
    if not args.regenerate_expected_groups:
        parser.error("regeneration requires --regenerate-expected-groups")
    _regenerate_expected_groups()
