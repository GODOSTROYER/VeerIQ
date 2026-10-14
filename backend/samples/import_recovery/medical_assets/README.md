# Medical asset supplies

## Incident

In tenant `atlas`, ASSET-88 is an oxygen sensor unit with a damaged on-hand quantity of `0`; the approved snapshot records `5`, while its bin remains `Dock 4`. ASSET-92 has a later edit and is tombstoned, so its current row must be preserved. ASSET-17 belongs to tenant `beacon` and is held; it is outside an `atlas` operator’s authority.

## Pack contents

- `current.csv` is the imported current inventory.
- `snapshot.json` contains the approved historical values.
- `authority.json` is separate current authority state for holds, revocations, tombstones, and later edits.
- `pack.json` defines the file mapping and approved snapshot digest; `APPROVAL.md` records what that digest means.

All data is synthetic. The sample demonstrates recovery of `quantity` and `location` only. The approved snapshot digest binds the sample file; it is not an external signature or real-world approval.
