import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from src.data import training_data_manager as tdm


def test_concurrent_auto_training_jsonl_writes_are_valid(tmp_path):
    output_path = tmp_path / "auto_training_corrections.jsonl"

    def append_task(task_id: int):
        corrections = [
            {
                "row_index": task_id * 10 + i,
                "after": f"Taxi-{task_id}",
                "value": f"payload-{task_id}-{i}",
            }
            for i in range(10)
        ]
        tdm.write_training_examples_to_file(corrections, output_path=output_path)

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(append_task, range(10)))

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100

    records = [json.loads(line) for line in lines]
    assert {record["row_index"] for record in records} == set(range(100))


def test_concurrent_pre_correction_cache_writes_are_atomic(tmp_path):
    original_cache_dir = tdm.PRE_CORRECTION_CACHE_DIR
    tdm.PRE_CORRECTION_CACHE_DIR = tmp_path
    try:
        sheet_id = "sheet-atomic"

        def save_task(task_id: int):
            df = pd.DataFrame({"task_id": [task_id], "tag": [f"task-{task_id}"]})
            tdm._save_pre_correction_state(sheet_id, df)

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(save_task, range(10)))

        cache_file = tdm._pre_correction_state_path(sheet_id)
        loaded = pd.read_json(cache_file, orient="split")
        assert loaded.shape == (1, 2)
        assert loaded.columns.tolist() == ["task_id", "tag"]
        assert isinstance(int(loaded.iloc[0]["task_id"]), int)
    finally:
        tdm.PRE_CORRECTION_CACHE_DIR = original_cache_dir
