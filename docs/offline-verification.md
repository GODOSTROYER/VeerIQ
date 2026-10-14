# Verify exported evidence offline

The verifier is a small standalone Python program. It imports only Python's standard library and `cryptography`; it does not load the VeerIQ app, its database, or application settings. Python 3.10 or newer and `cryptography` are required.

Run the acceptance checks from any directory with one command:

```sh
python3 /absolute/path/to/flow/scripts/test_veeriq_verify.py
```

This checks the public valid sample, a deliberately tampered copy, execution receipt digests, rejection of an unknown schema, and operation from outside the application environment. It exits nonzero on any failure.

Verify an exported file with the repository's pinned public operator key:

```sh
/absolute/path/to/flow/scripts/veeriq-verify /path/to/sealed-evidence.json
```

To check signer identity, obtain the expected Ed25519 public key through a separate trusted channel and pass it explicitly:

```sh
/absolute/path/to/flow/scripts/veeriq-verify /path/to/sealed-evidence.json --trusted-key /path/to/trusted-public-key.pem
```

The verifier checks the payload's canonical SHA-256 digest, event sequence and linked digests, Ed25519 signature, signer key fingerprint, and every serialized execution receipt digest. Unknown envelope schemas and unknown envelope or signature fields fail closed. It prints the plan hash when the export includes one. Audit report IDs are reported as unavailable when the export does not contain them; the verifier does not infer IDs from nearby fields.

The default key is [operator-public-key.pem](../verification/operator-public-key.pem), copied from the public key that accompanies the recorded export. That bundled key proves consistency with the repository's copy. For independent signer identity, use a key obtained separately. A signature and valid digest chain establish integrity relative to the signing key, not ArmorIQ attestation, an independent witness, or truth of the recorded claims.

Public examples are [valid-live-recovery.json](../verification/samples/valid-live-recovery.json) and [tampered-live-recovery.json](../verification/samples/tampered-live-recovery.json). They use the existing exported evidence, whose export path applies the project's credential redaction, and contain synthetic demo records.

## Recorded live audit linkage

`docs/evidence/merged/audit-linked-scripted-live-sealed.json` is a scripted repair using live ArmorIQ. Verify it with the published operator key. Its signed payload contains the ArmorIQ plan hash and five audit IDs returned by the service. These support online cross-checking; offline verification proves payload integrity, not sponsor attestation or server existence. Legacy exports without IDs still report them unavailable.
