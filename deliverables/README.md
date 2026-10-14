# Submission package

The submission archive is not committed to this repository. `scripts/package_submission.py` builds it on demand into this folder. Git ignores the outputs (see `.gitignore`).

Hosted CI passes for the commit recorded in [`docs/evidence/hosted-ci.json`](../docs/evidence/hosted-ci.json): the `test-build` and `secret-scan` jobs succeed. The `live-checks` job is skipped, because it runs only on manual dispatch with repository secrets.

Read [`README.md`](../README.md) and [`docs/submission.md`](../docs/submission.md) first.

## Build

Run from the repository root, after committing the source you want to submit:

```sh
backend/.venv/bin/python scripts/package_submission.py
```

It writes three files here:

- `veeriq-recovery-source.tar.gz`: every file Git tracks, under a `veeriq/` directory.
- `veeriq-recovery-source.tar.sha256`: the SHA-256 digest of the archive.
- `package-check.json`: the build time, file count, archive size and digest, the HEAD commit, and the results of the two checks.

Because only tracked files are archived, local files such as `.env`, `.data/` and dependency folders are left out, along with Git metadata. The archive does include the tracked docs, evidence, screenshots, sample packs and the recorded video. The script copies files as they are on disk, and `package-check.json` records HEAD. Commit your changes before you build, so the archive and the recorded commit match.

## Checks

Before it writes the archive, the script stops if a tracked file:

- is a `.env` file other than `.env.example`, or sits in a `.data` folder;
- contains a PEM private key block;
- contains a value from your local `.env` that is longer than 15 characters, differs from the public default, and sits under a name containing KEY, SECRET, TOKEN, PASSWORD, DSN, DATABASE_URL or CONNECTION_STRING.

The error message does not print the value.

## Verify and unpack

```sh
shasum -a 256 -c veeriq-recovery-source.tar.sha256
tar -xzf veeriq-recovery-source.tar.gz
cd veeriq
npm run setup
npm run dev
```

Setup creates local configuration from `.env.example`. Its default planning and enforcement are scripted and simulated. Real provider integrations need credentials supplied privately, and production OIDC needs a real configured provider.
