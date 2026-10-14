#!/usr/bin/env python3
"""Verify a RewindSafe sealed evidence JSON export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rewindsafe.runtime.sealed_evidence import load_public_key, verify_sealed_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="sealed evidence JSON file")
    parser.add_argument(
        "--public-key",
        type=Path,
        help="separately trusted Ed25519 public key in PEM or base64 raw format",
    )
    args = parser.parse_args()
    try:
        envelope = json.loads(args.evidence.read_text(encoding="utf-8"))
        trusted = load_public_key(args.public_key) if args.public_key else None
        result = verify_sealed_evidence(envelope, trusted)
    except Exception as exc:  # noqa: BLE001 - report input/IO errors in the same concise format
        result = {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("valid"):
        if result.get("signer_identity_trusted") is False:
            print("FAILED: embedded signing key does not match --public-key", file=sys.stderr)
            return 2
        return 1
    if args.public_key is None:
        print(
            "NOTICE: no --public-key given; only integrity was checked and the signer was NOT verified",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
