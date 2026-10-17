#!/usr/bin/env python3
"""Pool the recorded live reliability batches into one summary.

Reads every ``evidence/reliability-*.json`` batch and writes ``evidence/SUMMARY.json`` plus an
identical copy bundled with the frontend. The batches were recorded on different code versions,
so the pooled counts describe what was observed and are not one controlled cohort.

Usage: python scripts/summarize_reliability.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "evidence"
OUTPUTS = (EVIDENCE_DIR / "SUMMARY.json", ROOT / "frontend" / "src" / "data" / "reliabilitySummary.json")
POISONED_TOOL = "restore_access_grant"
CAVEAT = (
    "Pooled across batches recorded on different code versions; this is what was observed, "
    "not one controlled cohort."
)


def _count(value: Any) -> int | None:
    """Number of forbidden effects observed, or None when the record carries no observation."""
    if isinstance(value, list):
        return len(value)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_batch(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    trials = data.get("trials") or []
    blocked_by: Counter[str] = Counter()
    row = {
        "file": path.name,
        "recorded_at": data.get("created_at"),
        "provider": data.get("provider"),
        "models": data.get("models"),
        "enforcement": data.get("enforcement"),
        "trials": len(trials),
        "acted": 0,
        "poisoned_action_attempted": 0,
        "poisoned_action_blocked": 0,
        "repairs_completed": 0,
        "forbidden_effects": 0,
        "records_with_effect_observation": 0,
        "records_unknown_effect_status": 0,
        "unknown_effect_records": [],
        "interrupted": 0,
    }
    for index, trial in enumerate(trials, start=1):
        if trial.get("status") == "interrupted":
            row["interrupted"] += 1
        if (_count(trial.get("proposals")) or 0) > 0:
            row["acted"] += 1
        if trial.get("attempted_restore"):
            row["poisoned_action_attempted"] += 1
            blocks = [b for b in (trial.get("blocked") or []) if b.get("tool") == POISONED_TOOL]
            if blocks:
                row["poisoned_action_blocked"] += 1
                for source in blocks[0].get("sources") or ["unknown"]:
                    blocked_by[source] += 1
        if trial.get("completed"):
            row["repairs_completed"] += 1
        effects = _count(trial.get("forbidden_effects"))
        if effects is None:
            row["records_unknown_effect_status"] += 1
            row["unknown_effect_records"].append(
                {"file": path.name, "trial": trial.get("trial", index), "status": trial.get("status")}
            )
        else:
            row["records_with_effect_observation"] += 1
            row["forbidden_effects"] += effects
    row["never_acted"] = row["trials"] - row["acted"]
    row["blocked_by"] = dict(sorted(blocked_by.items()))
    return row


def build_summary() -> dict[str, Any]:
    batches = [summarize_batch(path) for path in sorted(EVIDENCE_DIR.glob("reliability-*.json"))]
    totals: dict[str, Any] = {
        key: sum(batch[key] for batch in batches)
        for key in (
            "trials",
            "acted",
            "never_acted",
            "interrupted",
            "poisoned_action_attempted",
            "poisoned_action_blocked",
            "repairs_completed",
            "forbidden_effects",
            "records_with_effect_observation",
            "records_unknown_effect_status",
        )
    }
    totals["records_total"] = totals["trials"]
    totals["unknown_effect_records"] = [rec for batch in batches for rec in batch["unknown_effect_records"]]
    blocked_by: Counter[str] = Counter()
    for batch in batches:
        blocked_by.update(batch["blocked_by"])
    totals["blocked_by"] = dict(sorted(blocked_by.items()))
    return {
        "schema": "veeriq.reliability-summary.v1",
        "scenario": "poisoned",
        "poisoned_tool": POISONED_TOOL,
        "caveat": CAVEAT,
        "totals": totals,
        "batches": batches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed summary is out of date")
    args = parser.parse_args()
    rendered = json.dumps(build_summary(), indent=2, sort_keys=True) + "\n"
    if args.check:
        stale = [str(p.relative_to(ROOT)) for p in OUTPUTS if not p.exists() or p.read_text(encoding="utf-8") != rendered]
        if stale:
            print("Reliability summary is out of date: " + ", ".join(stale), file=sys.stderr)
            print("Run: python scripts/summarize_reliability.py", file=sys.stderr)
            return 1
        print("Reliability summary is current.")
        return 0
    for path in OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
    totals = json.loads(rendered)["totals"]
    print(
        f"{totals['poisoned_action_blocked']}/{totals['poisoned_action_attempted']} poisoned actions blocked, "
        f"{totals['repairs_completed']}/{totals['acted']} repairs completed, "
        f"{totals['forbidden_effects']} forbidden effects observed in {totals['records_with_effect_observation']} of "
        f"{totals['records_total']} records; {totals['records_unknown_effect_status']} records have unknown effect status."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
