#!/usr/bin/env python3
"""Verify a VeerIQ/RewindSafe sealed evidence export without loading the app."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - environment-specific diagnostic
    print("Verification needs the 'cryptography' package. Install it with: python -m pip install cryptography", file=sys.stderr)
    raise SystemExit(3)

SCHEMA = "rewindsafe.sealed-evidence.v1"
ISSUER = "rewindsafe.local"
ZERO_DIGEST = "sha256:" + "0" * 64
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DEFAULT_KEY = Path(__file__).resolve().parents[1] / "verification" / "operator-public-key.pem"


class VerificationError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    """Match RewindSafe canonical JSON for its JSON-native exported values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise VerificationError(f"JSON contains duplicate key {key!r}")
        obj[key] = value
    return obj


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_no_duplicates,
                          parse_constant=lambda value: (_ for _ in ()).throw(VerificationError(f"invalid JSON number {value}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"could not read JSON export: {exc}") from exc


def load_public_key(path: Path) -> tuple[Ed25519PublicKey, bytes]:
    try:
        data = path.read_bytes()
        if data.startswith(b"-----BEGIN"):
            key = serialization.load_pem_public_key(data)
            if not isinstance(key, Ed25519PublicKey):
                raise VerificationError("trusted key is not an Ed25519 public key")
            raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            return key, raw
        try:
            raw = base64.b64decode(data.strip(), validate=True)
        except (ValueError, base64.binascii.Error):
            raw = data
        return Ed25519PublicKey.from_public_bytes(raw), raw
    except VerificationError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise VerificationError(f"could not load trusted Ed25519 public key: {exc}") from exc


def verify_event_chain(payload: dict[str, Any], supplied: Any, statement: dict[str, Any]) -> int:
    events = payload.get("events")
    if not isinstance(events, list):
        raise VerificationError("payload.events must be a list")
    if not isinstance(supplied, list) or len(supplied) != len(events):
        raise VerificationError("event chain length does not match the exported events")
    previous = ZERO_DIGEST
    previous_seq = 0
    for index, (event, node) in enumerate(zip(events, supplied), start=1):
        if not isinstance(event, dict) or not isinstance(node, dict):
            raise VerificationError(f"event {index} or its chain entry is not an object")
        # PostgreSQL allocates seq globally across runs, so a run may start above
        # one and have gaps from other runs. Continuity is proven by signed links.
        expected_seq = event.get("seq")
        if type(expected_seq) is not int or expected_seq <= previous_seq:
            raise VerificationError(f"event sequence is not strictly increasing at position {index}")
        previous_seq = expected_seq
        if node.keys() != {"seq", "event_digest", "previous", "digest"}:
            raise VerificationError(f"event chain entry {index} has an unknown shape")
        if node.get("seq") != expected_seq:
            raise VerificationError(f"event chain sequence is discontinuous at position {index}")
        if node.get("previous") != previous:
            raise VerificationError(f"event chain link {index} does not match the previous event")
        if node.get("event_digest") != digest(event):
            raise VerificationError(f"event {index} digest does not match its exported contents")
        body = {"seq": node["seq"], "event_digest": node["event_digest"], "previous": node["previous"]}
        calculated = digest(body)
        if node.get("digest") != calculated:
            raise VerificationError(f"event chain digest {index} is invalid")
        previous = calculated
    expected_head = previous if events else ZERO_DIGEST
    if statement.get("event_count") != len(events) or statement.get("event_chain_head") != expected_head:
        raise VerificationError("signed event count or chain head does not match the exported event chain")
    run_id = payload.get("run", {}).get("run_id") if isinstance(payload.get("run"), dict) else None
    if not run_id:
        raise VerificationError("payload.run.run_id is missing")
    if any(event.get("run_id") != run_id for event in events):
        raise VerificationError("an event belongs to a different run")
    return len(events)


def verify_receipt_digests(value: Any) -> int:
    """Check each serialized ExecutionReceipt digest found in the export."""
    checked = 0

    def visit(node: Any) -> None:
        nonlocal checked
        if isinstance(node, dict):
            if "receipt_digest" in node:
                receipt_digest = node.get("receipt_digest")
                if not isinstance(receipt_digest, str) or not DIGEST_RE.fullmatch(receipt_digest):
                    raise VerificationError("receipt has a missing or malformed receipt_digest")
                if digest({key: item for key, item in node.items() if key != "receipt_digest"}) != receipt_digest:
                    raise VerificationError("an execution receipt digest does not match its contents")
                checked += 1
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return checked


def verify(envelope: Any, trusted_key: Ed25519PublicKey, trusted_raw: bytes) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise VerificationError("export envelope must be a JSON object")
    if envelope.get("schema") != SCHEMA:
        raise VerificationError(f"unsupported evidence schema {envelope.get('schema')!r}; refusing to verify unknown formats")
    if envelope.keys() != {"schema", "payload", "payload_digest", "event_chain", "signature"}:
        raise VerificationError("evidence envelope has missing or unknown fields")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise VerificationError("payload must be an object")
    if payload.get("contract_version") != "1.0":
        raise VerificationError(f"unsupported payload contract version {payload.get('contract_version')!r}; refusing to verify unknown formats")
    signature = envelope.get("signature")
    if not isinstance(signature, dict) or signature.keys() != {"statement", "public_key", "key_fingerprint", "signature"}:
        raise VerificationError("signature block has missing or unknown fields")
    statement = signature.get("statement")
    if not isinstance(statement, dict) or statement.keys() != {
        "schema", "issuer", "algorithm", "run_id", "payload_digest", "event_count", "event_chain_head", "signed_at"
    }:
        raise VerificationError("signed statement has missing or unknown fields")
    if statement.get("schema") != SCHEMA or statement.get("issuer") != ISSUER or statement.get("algorithm") != "Ed25519":
        raise VerificationError("signed statement has an unsupported schema, issuer, or signature algorithm")
    calculated_payload = digest(payload)
    if envelope.get("payload_digest") != calculated_payload or statement.get("payload_digest") != calculated_payload:
        raise VerificationError("payload digest does not match the exported payload")
    receipts_checked = verify_receipt_digests(payload)
    run_id = payload.get("run", {}).get("run_id") if isinstance(payload.get("run"), dict) else None
    if not isinstance(run_id, str) or statement.get("run_id") != run_id:
        raise VerificationError("signed run ID does not match the exported payload")
    event_count = verify_event_chain(payload, envelope.get("event_chain"), statement)

    try:
        embedded_raw = base64.b64decode(signature["public_key"], validate=True)
        embedded = Ed25519PublicKey.from_public_bytes(embedded_raw)
        sig = base64.b64decode(signature["signature"], validate=True)
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise VerificationError("signature contains invalid base64 or an invalid Ed25519 public key") from exc
    fingerprint = "sha256:" + hashlib.sha256(embedded_raw).hexdigest()
    if signature.get("key_fingerprint") != fingerprint:
        raise VerificationError("embedded public key fingerprint is invalid")
    try:
        embedded.verify(sig, canonical_json(statement).encode("utf-8"))
    except InvalidSignature as exc:
        raise VerificationError("Ed25519 signature is invalid") from exc
    if embedded_raw != trusted_raw:
        raise VerificationError("signature is valid, but the signer does not match the trusted public key")

    plan_hash = None
    plan = payload.get("plan")
    if isinstance(plan, dict) and isinstance(plan.get("plan_hash"), str):
        plan_hash = plan["plan_hash"]
    audit_report_ids: list[str] = []

    def collect_audit_report_ids(node: Any) -> None:
        if isinstance(node, dict):
            value = node.get("audit_report_id")
            if isinstance(value, str) and value and value not in audit_report_ids:
                audit_report_ids.append(value)
            for item in node.values():
                collect_audit_report_ids(item)
        elif isinstance(node, list):
            for item in node:
                collect_audit_report_ids(item)

    collect_audit_report_ids(payload)

    return {
        "valid": True,
        "run_id": run_id,
        "event_count": event_count,
        "payload_digest": calculated_payload,
        "receipt_digests_checked": receipts_checked,
        "plan_hash": plan_hash,
        "audit_report_ids": audit_report_ids,
        "audit_report_ids_available": bool(audit_report_ids),
        "trusted_key_fingerprint": fingerprint,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="sealed evidence JSON export")
    parser.add_argument("--trusted-key", "--public-key", dest="trusted_key", type=Path, default=DEFAULT_KEY,
                        help=f"independently trusted Ed25519 public key (default: {DEFAULT_KEY})")
    args = parser.parse_args()
    try:
        trusted, trusted_raw = load_public_key(args.trusted_key)
        result = verify(load_json(args.evidence), trusted, trusted_raw)
    except VerificationError as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # malformed structures should always fail closed with a human-readable error
        print(f"Verification failed: malformed or unsupported evidence ({exc})", file=sys.stderr)
        return 1

    print(f"VERIFIED run {result['run_id']}")
    print(f"Payload SHA-256: {result['payload_digest']}")
    print(f"Event chain: {result['event_count']} events, sequence and links valid")
    print(f"Execution receipt digests: {result['receipt_digests_checked']} checked")
    print(f"Ed25519 signature: valid; trusted key {result['trusted_key_fingerprint']}")
    if result["plan_hash"]:
        print(f"Plan hash: {result['plan_hash']}")
    else:
        print("Plan hash: unavailable in this export")
    if result["audit_report_ids_available"]:
        print("Audit report IDs: " + ", ".join(result["audit_report_ids"]))
    else:
        print("Audit report IDs: unavailable in this export")
    print("Trust note: the default key is bundled with this repository; obtain it independently to verify signer identity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
