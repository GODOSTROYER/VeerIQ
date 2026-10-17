# What we learned building on ArmorIQ

Notes from building VeerIQ's recovery agent on `armoriq-sdk` 0.6.10 with live enforcement, written for the ArmorIQ team and for judges scoring takeaways. Everything here was observed in this repository; where we only planned something, we say so.

## What worked

1. **Plan binding stops a hijacked agent cold, and it is deterministic.** The backup carries a planted note telling the agent to call `restore_access_grant`. A live model (gpt-oss-120b on Groq) followed it in 23 of 84 recorded runs; ArmorIQ blocked all 23 with `tool-not-in-plan`, before our code ran. No prompt engineering was needed: the model was never warned about the note ([evidence/SUMMARY.json](../evidence/SUMMARY.json)).
2. **The console makes enforcement legible.** Each run is a session in Observability; the trace shows the `policy.deny` span with decision `Deny`, enforcement `block` and the reason, next to the `Allow` spans for the permitted tools. That is what we show judges instead of asking them to trust our UI.
3. **A too-wide plan is still caught.** When a plan that *included* `restore_access_grant` was signed, the backend allowlist still refused the call (`tool_not_in_allowlist`): two independent layers on ArmorIQ's side ([sponsor-policy-denial.json](evidence/merged/sponsor-policy-denial.json)).
4. **Registration as code.** `python tasks.py armoriq-register` creates the agent, the MCP server and the policy (5 allowed, 1 denied) from [armoriq/armoriq.yaml](../armoriq/armoriq.yaml), so a new workspace is one command.

## What we had to build next to it

1. **Tools are checked, arguments are not.** ArmorIQ decides *which* tool may run, not *which rows or fields* it may touch. A permitted `prepare_repair_manifest` could still target another tenant's order or an unrepairable column. VeerIQ adds a grant-scope gate and domain rules on the server-derived arguments (six gates in total), and the executor re-checks everything inside one locked transaction. Data rules have to live next to the data.
2. **Approvals for high-value repairs are VeerIQ's own today.** We built the HOLD round trip (delegation id, polling, re-check after approval) and unit-tested it with fakes, but an amount-based hold rule could not be applied in our workspace's Policy Studio, and an isolated $12,400 call still returned ALLOW ([armoriq-hold-setup.md](armoriq-hold-setup.md)). The $12,400 approval in the demo is VeerIQ's second-reviewer step, bound to the exact payload digest, and is labelled that way.
3. **We verify our own records offline.** ArmorIQ's audit is server-side; judges and auditors also want something they can check without network access. Every VeerIQ run ends in a hash-chained, Ed25519-signed receipt that the start page verifies in the browser and `scripts/veeriq-verify` verifies on the command line.

## Numbers from this workspace

| What | p50 | p95 | Count |
|---|---|---|---|
| Per-action enforcement check (`check`) | 828 ms | 1.56 s | 162 |
| Plan capture and token issuance | 4.29 s | 7.55 s | 31 |

From the local `/api/metrics` endpoint on 17 Oct 2026; it pools every recorded live decision in this workspace's database, so treat it as indicative, not a benchmark. A recovery run makes 5–7 checks, so enforcement adds a few seconds to a run that waits far longer on the model.

## What we would ask for

- **Argument-level policy** (row and field constraints, amount thresholds on server-derived values), so the grant-scope gate could move into ArmorIQ.
- **Amount-based holds for custom MCP tools** in Policy Studio, with the approver acting from the console, so a high-value repair is held by ArmorIQ itself.
- **A published IAP public key**, so plan tokens can be verified locally and offline, like our receipts.
- **Tool discovery for local MCP servers**: the registry shows `rewindsafe-recovery` with 0/0 tools because the server runs on localhost.
