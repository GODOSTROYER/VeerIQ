# Limitations

Stated plainly so nobody has to find them.

## Evidence

- **Live ArmorIQ is verified for plan binding, allow and the org allowlist** (2026-10-07, `evidence/gate-a-early-live-2026-10-07.md`). **No amount HOLD is configured** in the workspace, so no ArmorIQ HOLD or approval round trip has been observed; the review scenario's hold is RewindSafe's reviewer.
- **Live LLM runs use Groq.** Evidence of model behavior under injection is `evidence/injection-eval-*.json` and the labeled live runs [run id]. Small trial counts: this shows what these models did in these trials, not a general rate.
- **Scripted planner runs are a deterministic re-enactment**, not evidence of how a model behaves under injection. The UI and run metadata label them as such.
- Offline runs use a labeled simulation (`simulated=true`, source `armoriq.offline_simulation`) that mirrors the *observed* live behavior (no amount HOLD; a wider plan is issued then blocked at check). It shows RewindSafe's integration shape, not ArmorIQ's decisions.
- Observed readiness depends on registration: before the workspace was registered, every check returned `no_matching_policy` (fail closed). A judge's own workspace needs `python tasks.py armoriq-register` first.

## Design

- **Argument binding is RewindSafe's, not ArmorIQ's.** Observed live: the same tool with `tenant=beacon` was allowed by ArmorIQ. The tool name is bound to the signed plan; parameters are not. Wrong-tenant and wrong-resource blocks therefore come from the grant layer.
- `report()` swallows errors, so audit delivery cannot be proven by a clean return. The outbox records attempts; "delivered" means the call returned without raising.
- Plan binding means a tool absent from the plan is blocked. If someone added `restore_access_grant` to the plan, plan binding alone would not stop it. Observed live: a wider plan containing it is still **issued**, and the org allowlist then blocks it at check time (`tool_not_in_allowlist`); the RewindSafe grant layer refuses it too.
- The offline simulation can drift from the real service. It is a stand-in, kept deliberately small, and updated to match observed live behavior.
- Prior art: `pg_restore --no-acl` and similar tooling already avoid restoring privileges. RewindSafe's contribution is value-level restore under current authority, with per-layer attribution, not a new backup format.

## Scope

- One workflow (order repair), one incident, synthetic data, two tenants. The runtime is structured so a second workflow adapter could reuse it; this is not yet demonstrated and none is shipped.
- Repairable fields are `total_cents`, `shipping_region`, `status`. Other fields are out of scope by design.
- Demo identities are local and the session cookie is a signed identity id. This is not production authentication or authorization.
- The fixture reset is for a disposable demo database and has no place in production.
- Concurrency is exercised with two-thread tests and PostgreSQL locks on a single database; it is not load-tested.
- The frontend targets modern desktop browsers; phone layout is best-effort.
- The MCP server exposes the same tools through the same dispatcher but needs an existing active run; it is not a general-purpose connector.
- Accessibility and reduced-motion support are implemented as specified but not formally audited.
