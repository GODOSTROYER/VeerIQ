import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from rewindsafe.runtime import sealed_evidence


def sample_payload():
    return {
        "run": {"run_id": "run_1", "created_at": datetime(2026, 10, 12, tzinfo=UTC)},
        "metrics": {"amount": Decimal("1.20")},
        "events": [
            {"seq": 1, "type": "run.created", "data": {"safe": True}},
            {"seq": 2, "type": "run.finished", "data": {"status": "completed"}},
        ],
    }


def test_seal_detects_payload_event_tampering_truncation_and_reorder():
    key = sealed_evidence.Ed25519PrivateKey.generate()
    envelope = sealed_evidence.seal_payload(sample_payload(), key)
    assert sealed_evidence.verify_sealed_evidence(envelope)["valid"] is True

    altered = {**envelope, "payload": {**envelope["payload"], "metrics": {"amount": "9.00"}}}
    assert sealed_evidence.verify_sealed_evidence(altered)["payload_digest_valid"] is False

    truncated = {**envelope, "payload": {**envelope["payload"], "events": envelope["payload"]["events"][:1]}}
    assert sealed_evidence.verify_sealed_evidence(truncated)["valid"] is False

    reordered = {
        **envelope,
        "payload": {**envelope["payload"], "events": list(reversed(envelope["payload"]["events"]))},
    }
    assert sealed_evidence.verify_sealed_evidence(reordered)["valid"] is False


def test_local_signer_key_persists_and_trusted_key_checks_identity(tmp_path):
    key_path = tmp_path / ".data" / "signing.pem"
    first = sealed_evidence._private_key(key_path)
    second = sealed_evidence._private_key(key_path)
    first_public = first.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    second_public = second.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    assert first_public == second_public
    if os.name != "nt":  # NTFS has no POSIX mode bits; Windows reports 0o666 for any writable file
        assert key_path.stat().st_mode & 0o777 == 0o600
        assert key_path.parent.stat().st_mode & 0o777 == 0o700

    envelope = sealed_evidence.seal_payload(sample_payload(), first)
    assert (
        sealed_evidence.verify_sealed_evidence(envelope, second.public_key())["signer_identity_trusted"]
        is True
    )
    other = sealed_evidence.Ed25519PrivateKey.generate().public_key()
    assert sealed_evidence.verify_sealed_evidence(envelope, other)["signer_identity_trusted"] is False


def test_public_pem_is_stable_and_matches_the_persistent_signer(tmp_path, monkeypatch):
    key_path = tmp_path / ".data" / "signing.pem"
    monkeypatch.setattr(sealed_evidence, "KEY_PATH", key_path)
    signer = sealed_evidence._private_key(key_path)
    envelope = sealed_evidence.seal_payload(sample_payload(), signer)

    first = sealed_evidence.public_key_pem()
    second = sealed_evidence.public_key_pem()
    trusted = sealed_evidence.load_public_key(first)
    assert first.startswith(b"-----BEGIN PUBLIC KEY-----")
    assert first == second
    assert sealed_evidence.verify_sealed_evidence(envelope, trusted)["signer_identity_trusted"] is True
    if os.name != "nt":
        assert key_path.stat().st_mode & 0o777 == 0o600


def test_verifier_separates_embedded_consistency_from_signer_identity():
    key = sealed_evidence.Ed25519PrivateKey.generate()
    envelope = sealed_evidence.seal_payload(sample_payload(), key)
    result = sealed_evidence.verify_sealed_evidence(envelope)
    assert result["valid"] is True
    assert result["signer_identity_trusted"] is None


def test_pinned_key_mismatch_fails_validity_while_integrity_details_still_pass():
    signer = sealed_evidence.Ed25519PrivateKey.generate()
    other = sealed_evidence.Ed25519PrivateKey.generate()
    envelope = sealed_evidence.seal_payload(sample_payload(), signer)

    mismatched = sealed_evidence.verify_sealed_evidence(envelope, other.public_key())
    assert mismatched["valid"] is False
    assert mismatched["signer_identity_trusted"] is False
    assert mismatched["payload_digest_valid"] is True
    assert mismatched["event_chain_valid"] is True
    assert mismatched["trust_basis"] == "pinned_key"

    pinned = sealed_evidence.verify_sealed_evidence(envelope, signer.public_key())
    assert pinned["valid"] is True
    assert pinned["signer_identity_trusted"] is True
    assert pinned["trust_basis"] == "pinned_key"

    embedded = sealed_evidence.verify_sealed_evidence(envelope)
    assert embedded["valid"] is True
    assert embedded["signer_identity_trusted"] is None
    assert embedded["trust_basis"] == "embedded_key_only"


def _load_cli():
    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_sealed_evidence.py"
    spec = importlib.util.spec_from_file_location("verify_sealed_evidence_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_exit_code_fails_on_pinned_key_mismatch(tmp_path, monkeypatch, capsys):
    cli = _load_cli()
    signer = sealed_evidence.Ed25519PrivateKey.generate()
    other = sealed_evidence.Ed25519PrivateKey.generate()
    export = tmp_path / "export.json"
    export.write_text(json.dumps(sealed_evidence.seal_payload(sample_payload(), signer)), encoding="utf-8")
    keys = {}
    for name, key in (("signer", signer), ("other", other)):
        keys[name] = tmp_path / f"{name}.pem"
        keys[name].write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    monkeypatch.setattr(sys, "argv", ["verify", str(export), "--public-key", str(keys["other"])])
    assert cli.main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["signer_identity_trusted"] is False
    assert "does not match --public-key" in captured.err

    monkeypatch.setattr(sys, "argv", ["verify", str(export), "--public-key", str(keys["signer"])])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["trust_basis"] == "pinned_key"

    monkeypatch.setattr(sys, "argv", ["verify", str(export)])
    assert cli.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["trust_basis"] == "embedded_key_only"
    assert "signer was NOT verified" in captured.err
