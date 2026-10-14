"""Locally signed, tamper-evident exports of durable RewindSafe run evidence.

The key is an operator-controlled local key. Its signature proves consistency with
the embedded public key; trust in the operator's identity must come from elsewhere.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from rewindsafe.config import REPO_ROOT
from rewindsafe.runtime.canonical import canonical_json, digest, to_jsonable, utcnow
from rewindsafe.runtime.receipts import build_evidence

ISSUER = "rewindsafe.local"
KEY_PATH = REPO_ROOT / ".data" / "evidence-signing-ed25519.pem"
SCHEMA = "rewindsafe.sealed-evidence.v1"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def _private_key(path: Path | None = None) -> Ed25519PrivateKey:
    path = path or KEY_PATH
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        key = Ed25519PrivateKey.generate()
        data = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # another request generated the persistent key first
            data = path.read_bytes()
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("local evidence signing key is not Ed25519")
    return key


def public_key_pem() -> bytes:
    """Return the persistent local signer's public key, never its private key."""
    return _private_key(KEY_PATH).public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def event_chain(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a sequence-sensitive digest chain over the exact exported event payloads."""
    chain: list[dict[str, Any]] = []
    previous = "sha256:" + "0" * 64
    for event in events:
        node = {
            "seq": event.get("seq"),
            "event_digest": digest(event),
            "previous": previous,
        }
        node["digest"] = digest(node)
        chain.append(node)
        previous = node["digest"]
    return chain


def seal_payload(payload: dict[str, Any], key: Ed25519PrivateKey) -> dict[str, Any]:
    normalized = to_jsonable(payload)
    events = normalized.get("events")
    if not isinstance(events, list):
        raise TypeError("evidence payload must contain an events list")
    chain = event_chain(events)
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    statement = {
        "schema": SCHEMA,
        "issuer": ISSUER,
        "algorithm": "Ed25519",
        "run_id": normalized.get("run", {}).get("run_id"),
        "payload_digest": digest(normalized),
        "event_count": len(events),
        "event_chain_head": chain[-1]["digest"] if chain else "sha256:" + "0" * 64,
        "signed_at": to_jsonable(utcnow()),
    }
    signature = key.sign(canonical_json(statement).encode("utf-8"))
    return {
        "schema": SCHEMA,
        "payload": normalized,
        "payload_digest": statement["payload_digest"],
        "event_chain": chain,
        "signature": {
            "statement": statement,
            "public_key": _b64(public_bytes),
            "key_fingerprint": "sha256:" + hashlib.sha256(public_bytes).hexdigest(),
            "signature": _b64(signature),
        },
    }


def build_sealed_evidence(run_id: str) -> dict[str, Any]:
    """Sign the existing read-only durable evidence bundle for a run."""
    return seal_payload(build_evidence(run_id), _private_key())


def load_public_key(value: str | bytes | Path) -> Ed25519PublicKey:
    """Load a separately trusted Ed25519 key from PEM, raw bytes, or base64 raw bytes."""
    if isinstance(value, Path):
        data = value.read_bytes()
    elif isinstance(value, str):
        candidate = Path(value)
        data = candidate.read_bytes() if candidate.exists() else value.encode("ascii")
    else:
        data = value
    if data.startswith(b"-----BEGIN"):
        key = serialization.load_pem_public_key(data)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("trusted public key is not Ed25519")
        return key
    try:
        decoded = _unb64(data.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        decoded = data
    return Ed25519PublicKey.from_public_bytes(decoded)


def verify_sealed_evidence(
    envelope: dict[str, Any], trusted_public_key: Ed25519PublicKey | None = None
) -> dict[str, Any]:
    """Verify payload, event chain, statement and embedded signature; pin the signer when a key is given.

    Without ``trusted_public_key`` the result proves internal consistency only: the envelope was not altered
    after signing with the key it carries. It does not prove who signed it, since anyone can produce such an
    envelope (``trust_basis`` is ``"embedded_key_only"``). Pass the workspace's own public key to check the
    signer; ``valid`` is then False unless the embedded key matches it (``trust_basis`` is ``"pinned_key"``).
    """
    try:
        payload = to_jsonable(envelope["payload"])
        events = payload["events"]
        signature = envelope["signature"]
        statement = signature["statement"]
        public_bytes = _unb64(signature["public_key"])
        embedded = Ed25519PublicKey.from_public_bytes(public_bytes)
        calculated_payload = digest(payload)
        calculated_chain = event_chain(events)
        chain_match = calculated_chain == envelope["event_chain"]
        payload_match = calculated_payload == envelope["payload_digest"] == statement["payload_digest"]
        statement_match = (
            statement.get("schema") == SCHEMA
            and statement.get("issuer") == ISSUER
            and statement.get("algorithm") == "Ed25519"
            and statement.get("run_id") == payload.get("run", {}).get("run_id")
            and statement.get("event_count") == len(events)
            and statement.get("event_chain_head")
            == (calculated_chain[-1]["digest"] if calculated_chain else "sha256:" + "0" * 64)
        )
        embedded.verify(_unb64(signature["signature"]), canonical_json(statement).encode("utf-8"))
        integrity = payload_match and chain_match and statement_match and envelope.get("schema") == SCHEMA
        trusted_match = None
        trust_basis = "embedded_key_only"
        if trusted_public_key is not None:
            trusted_raw = trusted_public_key.public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            )
            trusted_match = trusted_raw == public_bytes
            trust_basis = "pinned_key"
        return {
            # A pinned key that does not match the embedded signer fails validity even if integrity passed.
            "valid": integrity and trusted_match is not False,
            "embedded_signature_valid": True,
            "payload_digest_valid": payload_match,
            "event_chain_valid": chain_match,
            "statement_valid": statement_match,
            "signer_identity_trusted": trusted_match,
            "trust_basis": trust_basis,
            "issuer": statement.get("issuer"),
            "key_fingerprint": signature.get("key_fingerprint"),
        }
    except Exception as exc:  # noqa: BLE001 - malformed input becomes a failed verification result
        return {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
