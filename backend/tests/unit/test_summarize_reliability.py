"""Missing forbidden-effect observations are unknown, never measured zeros."""

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "summarize_reliability", Path(__file__).resolve().parents[3] / "scripts" / "summarize_reliability.py"
)
summarize = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summarize)


def test_missing_effect_observation_is_unknown(tmp_path):
    batch = tmp_path / "reliability-x.json"
    batch.write_text(
        json.dumps({"trials": [
            {"trial": 1, "status": "succeeded", "forbidden_effects": 0, "proposals": [1]},
            {"trial": 2, "status": "interrupted"},
            {"trial": 3, "status": "interrupted", "forbidden_effects": None},
            {"trial": 4, "status": "succeeded", "forbidden_effects": 2},
        ]}),
        encoding="utf-8",
    )
    row = summarize.summarize_batch(batch)
    assert row["trials"] == 4
    assert row["records_with_effect_observation"] == 2
    assert row["records_unknown_effect_status"] == 2
    assert row["forbidden_effects"] == 2
    assert [r["trial"] for r in row["unknown_effect_records"]] == [2, 3]


def test_committed_summary_counts_unknown_records():
    totals = json.loads((Path(summarize.EVIDENCE_DIR) / "SUMMARY.json").read_text(encoding="utf-8"))["totals"]
    assert totals["records_total"] == 84
    assert totals["records_with_effect_observation"] + totals["records_unknown_effect_status"] == 84
