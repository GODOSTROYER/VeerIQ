# Warehouse stock locations

## Incident

In tenant `atlas`, SKU-402 has a damaged on-hand quantity of `0` and a missing bin. Its approved snapshot records quantity `140` and bin `A-03-C`, so those two fields are eligible for recovery. SKU-511 is held, SKU-512 has a later edit, and both must keep their current values. SKU-019 belongs to tenant `beacon` and is revoked; an `atlas` grant cannot read or repair it.

## Pack contents

- `current.json` is the imported current inventory.
- `snapshot.json` contains the approved historical values.
- `authority.json` is separate current authority state for holds, revocations, tombstones, and later edits.
- `pack.json` defines the file mapping and approved snapshot digest; `APPROVAL.md` records what that digest means.

All data is synthetic. The sample demonstrates recovery of `quantity` and `location` only. The approved snapshot digest binds the sample file; it is not an external signature or real-world approval.
