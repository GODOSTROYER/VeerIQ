# Domain components

Shared building blocks for every page. Import from `@/components/domain`. UI primitives are in `@/components/ui`.
All colours come from `src/styles/tokens.css`; layer, source and outcome metadata comes from `src/lib/layers.ts`.
Never label a VeerIQ decision as ArmorIQ: `SourceBadge` derives its label from `Decision.source` and marks `simulated` decisions with a dashed outline and a SIMULATED marker.

## DefenseStack

```tsx
<DefenseStack decisions={bundle.decisions} animateKey={bundle.proposal.proposal_id} compact? />
```

| prop | type | notes |
|---|---|---|
| `decisions` | `Decision[]` | all decisions of ONE proposal (decisive, allowed, shadow) |
| `compact` | `boolean` | hides the reason text under the stopping layer |
| `animateKey` | `string` | change it (e.g. selected proposal id) to replay the entrance |

Rows: ArmorIQ, Grant scope, Domain, Second reviewer, PostgreSQL (a Runtime row is added on top only when a runtime check blocked).
The first non-shadow, non-allow decision of a layer glows and says "Stopped here" (or "Held here" / "failed closed"). Allowed layers show a check, shadow blocks say "Would also block", untouched layers dim.

## DecisionCard

```tsx
<DecisionCard decision={d} defaultOpen? footer? />
```
Outcome chip, source badge, latency, headline and reason in plain English. "Technical details" expands: rule, source id, ArmorIQ sponsor evidence (mode, session mode, SDK version, raw action, matched policy, delegation, plan id, plan hash) and sanitized JSON.
Shadow decisions are drawn dashed. `footer` is for extra content such as "Handler entries: 0".

## OrderDiffTable

```tsx
<OrderDiffTable rows={snapshotDiff} repairedIds? after? foreignOrderIds? targetIds? onRowClick? compact? emptyState? />
```
`rows` is `SnapshotDiffRow[]` from `/app/snapshot-diff`. Columns: Order, Order total, Shipping region, Order status, State.
- damaged cell: current value in red over "snapshot X"
- `repairedIds`: those cells morph red to green (CSS `morph-good`) and show "was X". To animate a live repair, keep the pre-repair rows in state and pass the repaired ids (a refetched diff no longer shows the difference).
- `after`: `Record<orderId, SnapshotOrderValues>` overrides the snapshot as the repaired value (e.g. from a receipt)
- `changed_after_snapshot` rows: blue current value with "Snapshot said X" (never restored), tag "Later update kept"
- `deleted_tombstoned` / `current === null`: struck-through snapshot value, tag "Deleted stays deleted"
- `foreignOrderIds`: tag "Other tenant", values shown muted
- `targetIds`: accent bar on the row the agent is working on

## ProtectedChecklist

```tsx
<ProtectedChecklist checks={invariantChecks} only? exclude? compact? />
```
Category icons; preserved/repaired in calm green; pending amber; violated loud red with glow and `role="alert"`.

## ScenarioCard

```tsx
<ScenarioCard scenario onLaunch={(s) => ...} featured? loading? disabled? disabledReason? />
```
`featured` defaults to `scenario.kind === 'flagship'` (larger, shows description and all highlights). `onLaunch` should draft a grant (`POST /grants/draft`) and open `GrantReview`.

## GrantSummary

```tsx
<GrantSummary grant variant="compact" | "full" simulated? />
```
`compact`: purpose, scope chips, tool and prohibition counts, expiry. `full`: Scope, Allowed tools (the signed plan), Needs a second reviewer, Hard prohibitions, Limits and expiry, Source snapshot with digests. Also exports `expiryCopy(grant)`.

## GrantReview

```tsx
<GrantReview open onClose grant={draft} scenario={spec} status={systemStatus} onStarted? />
```
Modal: summary, planner choice (Auto, Scripted, Live LLM; the last is disabled with an explanation when `status.planner.configured_llm` is false), hold-to-confirm. On confirm: `POST /grants/{id}/authorize`, `POST /runs`, then navigates to `/runs/:id` (or calls `onStarted(run)`).

## ModeBanner, EnforcementBadge, PlannerBadge

```tsx
<ModeBanner status={systemStatus} />      // global SIMULATED strip + server warnings
<EnforcementBadge status={systemStatus} /> // "Live ArmorIQ" or dashed "Simulated"
<PlannerBadge status={systemStatus} />
```

## IdentitySwitcher

```tsx
<IdentitySwitcher />
```
Uses `useSession()`. Menu is labelled "Local demo identities" and includes Sign out (the single account surface).
