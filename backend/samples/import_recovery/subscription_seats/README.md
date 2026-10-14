# Subscription seat inventory

## Incident

In tenant `atlas`, the Billing Pro seat count has fallen to `0`; the approved snapshot records `8`, while the assigned team location remains unchanged. The analytics seat record has a later edit and must retain its current count. The support seat record belongs to tenant `beacon`, is tombstoned and revoked, and must remain outside an `atlas` recovery.

## Pack contents

- `current.csv` is the imported current inventory.
- `snapshot.json` contains the approved historical values.
- `authority.json` is separate current authority state for holds, revocations, tombstones, and later edits.
- `pack.json` defines the file mapping and approved snapshot digest; `APPROVAL.md` records what that digest means.

All data is synthetic. The sample demonstrates recovery of `quantity` and `location` only. The approved snapshot digest binds the sample file; it is not an external signature or real-world approval.
