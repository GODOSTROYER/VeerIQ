"""Build the tracked submission source; never include local secrets or state.

Run from the repository root with backend/.venv/bin/python scripts/package_submission.py.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import tarfile

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
files = [Path(item) for item in subprocess.check_output(
    ['git', 'ls-files', '-z'], cwd=root).decode().split('\0') if item]
public_defaults = dotenv_values(root / '.env.example')
secret_values = [value.encode() for key, value in dotenv_values(root / '.env').items()
                 if value and len(value) > 15 and value != public_defaults.get(key) and
                 any(tag in key.upper() for tag in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'DSN', 'DATABASE_URL', 'CONNECTION_STRING'))]
for item in files:
    raw = (root / item).read_bytes()
    if (item.name == '.env' or item.name.startswith('.env.') and item.name != '.env.example'
            or '.data' in item.parts
            or re.search(rb'(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', raw)
            or any(value in raw for value in secret_values)):
        raise SystemExit('Sensitive content detected; package blocked. No credential value is displayed.')
folder = root / 'deliverables'
folder.mkdir(exist_ok=True)
archive = folder / 'veeriq-recovery-source.tar.gz'
with tarfile.open(archive, 'w:gz') as output:
    for item in files:
        output.add(root / item, arcname='veeriq/' + str(item), recursive=False)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(folder / 'veeriq-recovery-source.tar.sha256').write_text(digest + '  ' + archive.name + '\n')
report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'tracked_files': len(files),
          'archive_bytes': archive.stat().st_size, 'archive_sha256': digest,
          'credential_value_scan': 'passed', 'private_key_exclusion': 'passed',
          'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()}
(folder / 'package-check.json').write_text(json.dumps(report, indent=2) + '\n')
print('Submission package built; credential and private-key exclusion checks passed.')
