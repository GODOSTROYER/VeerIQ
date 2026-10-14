#!/usr/bin/env python3
"""Black-box acceptance checks for the standalone evidence verifier."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "veeriq-verify"
SAMPLES = ROOT / "verification" / "samples"


class StandaloneVerifierAcceptance(unittest.TestCase):
    def invoke(self, evidence: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [str(VERIFY), str(evidence)], cwd=tempfile.gettempdir(), env=env,
            text=True, capture_output=True, check=False,
        )

    def test_public_valid_export_verifies_and_checks_receipt_digests(self) -> None:
        result = self.invoke(SAMPLES / "valid-live-recovery.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VERIFIED run", result.stdout)
        self.assertIn("Execution receipt digests: 2 checked", result.stdout)
        self.assertIn("Audit report IDs: unavailable in this export", result.stdout)

    def test_tampered_public_export_fails(self) -> None:
        result = self.invoke(SAMPLES / "tampered-live-recovery.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Verification failed:", result.stderr)

    def test_live_import_global_event_sequence_verifies(self) -> None:
        result = self.invoke(ROOT / "docs/evidence/merged/import-live-sealed.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Event chain: 36 events", result.stdout)

    def test_unknown_schema_fails_closed(self) -> None:
        envelope = json.loads((SAMPLES / "valid-live-recovery.json").read_text())
        envelope["schema"] = "rewindsafe.sealed-evidence.v999"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown-schema.json"
            path.write_text(json.dumps(envelope))
            result = self.invoke(path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to verify unknown formats", result.stderr)

    def test_unknown_payload_contract_fails_closed(self) -> None:
        envelope = json.loads((SAMPLES / "valid-live-recovery.json").read_text())
        envelope["payload"]["contract_version"] = "9.9"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown-contract.json"
            path.write_text(json.dumps(envelope))
            result = self.invoke(path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsupported payload contract version", result.stderr)

    def test_changed_receipt_fails_integrity_validation(self) -> None:
        envelope = json.loads((SAMPLES / "valid-live-recovery.json").read_text())
        receipt = envelope["payload"]["proposals"][-1]["receipt"]
        receipt["result"] = "rolled_back"
        payload_bytes = json.dumps(
            envelope["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        payload_digest = "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
        envelope["payload_digest"] = payload_digest
        envelope["signature"]["statement"]["payload_digest"] = payload_digest
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed-receipt.json"
            path.write_text(json.dumps(envelope))
            result = self.invoke(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("execution receipt digest does not match", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
