# Local evidence capture

Captured October 12, 2026 from the running VeerIQ application. This is a deterministic adversarial replay using real local MCP handlers, the application protocol gate and synthetic FLOW-42 data. ArmorIQ and model credentials were not configured.

The completed run `25cc8f32-13a7-4e0e-bb63-ac2af91b42b3` denied export, identifier access and the narrowed worker's publication attempt. Each permitted research handler ran once; aggregate publication ran once after exact-artifact approval. The separate canary recorded zero requests and zero bytes.

- `local-replay-receipt.json`: locally signed scope, final run state and 16 hash-linked events.
- `local-replay-effects.json`: independent canary and MCP-handler observations captured while the process was still running. This snapshot is not part of the signed receipt.
- `local-replay-public-key.pem`: the local signer's public key, supplied separately for reproducible verification. Shipping the key with the evidence establishes consistency; it does not independently establish signer identity.

Verify from the project root:

```sh
npm run verify-receipt -- docs/evidence/local-replay-receipt.json docs/evidence/local-replay-public-key.pem
```

Verification passed for all 16 events. These files contain no private signing key, credentials or real participant data. They demonstrate this run's local behavior, not verified sponsor enforcement or general prompt-injection resistance.
