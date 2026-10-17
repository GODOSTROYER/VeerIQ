# Docs index

Start with the [README](../README.md) at the repository root. The files below are grouped by use. The working notes describe earlier states of the project in places; the start-here files describe the current state.

## Start here

- [submission-status.md](submission-status.md): single source of current truth (links, CI, mode labels, what each proof proves).
- [submission.md](submission.md): the submission write-up for ArmorIQ Flow State.
- [demo-script.md](demo-script.md): the two-minute demo script, to be recorded with a live model and live ArmorIQ.
- [architecture.md](architecture.md): the React workspace, FastAPI backend, PostgreSQL state and the shared dispatcher.
- [limitations.md](limitations.md): current limitations, with the claims that remain unverified or out of scope.
- [offline-verification.md](offline-verification.md): how to verify an exported evidence file with the standalone verifier.
- [production-operations.md](production-operations.md): production deployment and identity setup, with the required OIDC and ArmorIQ settings and the production safeguards.
- [local-oidc-rehearsal.md](local-oidc-rehearsal.md): an optional local Keycloak rehearsal of VeerIQ's OIDC sign-in.
- [import-postgres-tls.md](import-postgres-tls.md): importing from a read-only PostgreSQL source over verified TLS.
- [reliability-batching.md](reliability-batching.md): collecting the full live reliability cohort across provider quota windows.

## Working notes

Internal development notes and evidence. Several describe an earlier state of the project.

- [armoriq-hold-setup.md](armoriq-hold-setup.md): dashboard steps and evidence requirements for a live ArmorIQ HOLD rehearsal.
- [merged-architecture.md](merged-architecture.md): an architecture description of the merged project: the VeerIQ workspace on the rewindsafe engine.
- [merged-demo-script.md](merged-demo-script.md): an alternate 90-second judge walkthrough; the two-minute script is [demo-script.md](demo-script.md).
- [merged-readiness.md](merged-readiness.md): a readiness summary for the merged project, built around the recorded live run.
- [credential-status.json](credential-status.json): a credential and tool-policy smoke check from 12 October 2026. No research tools ran.
- [dispatch-baseline.sha256](dispatch-baseline.sha256): the SHA-256 digest of the dispatcher baseline, cited by [architecture.md](architecture.md).
- [rewindsafe-origin/](rewindsafe-origin/): pre-event documents for the rewindsafe engine: build contract, runbook, SDK integration notes, event requirements, limitations, and provenance and eligibility in `attribution.md`.
- [evidence/](evidence/): captured checks and exports: the hosted CI record, UI audits, offline verification results, the local OIDC rehearsal, and sealed exports and checks in `merged/`. The recorded live reliability batches are in the repository's root [`evidence/`](../evidence/) folder.
- [img/](img/): screenshots of the main pages at 390, 1280, 1440 and 1920 pixel widths.
- [video/](video/): the 43-second recorded demo, `veerIQ-demo.webm`.
