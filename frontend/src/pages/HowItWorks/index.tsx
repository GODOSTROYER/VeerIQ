import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Check, Info, TriangleAlert } from 'lucide-react'
import { useSystemStatus } from '@/api/hooks'

import { Badge, Button, Disclosure, EmptyState, ErrorState, Panel, Skeleton } from '@/components/ui'
import { EnforcementTable } from './EnforcementTable'
import { FlowDiagram } from './FlowDiagram'
import { Story } from './Story'

function SectionHead({ id, title, children }: { id: string; title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 max-w-2xl">
      <h2 id={id} className="text-2xl font-semibold tracking-[-0.025em] text-ink">
        {title}
      </h2>
      {children && <p className="mt-1.5 text-[14px] leading-relaxed text-ink-2">{children}</p>}
    </div>
  )
}

const EXISTING = [
  'pg_restore --no-acl already skips the privilege statements in a dump, so a restore need not bring old grants back.',
  'Snapshots, point-in-time recovery and row-level restore tools return data to an earlier state.',
]

const CONTRIBUTIONS = [
  {
    title: 'Authority scoped to the incident',
    body: 'The agent gets a grant for one incident: named records, named fields, one tenant, a time limit. Skipping privileges at restore time does not do that. It limits what the restore carries, not what an agent may attempt.',
  },
  {
    title: 'Checks against current state',
    body: 'Before every write, today’s data is compared with the snapshot: deletions, holds, newer edits and row versions. Old data never overwrites a newer decision.',
  },
  {
    title: 'Constrained replanning',
    body: 'When a layer says no, the agent may adapt, but only inside the grant it started with. A new plan cannot widen it.',
  },
  {
    title: 'Boundaries you can verify',
    body: 'A verification suite replays forbidden actions through the real code path and reports which layer stopped each one, with evidence.',
  },
]

const LIMITS = [
  'ArmorIQ’s SDK path used here binds the tool name to the signed plan. It does not bind argument values. Wrong-tenant and wrong-order requests are refused by VeerIQ’s grant and manifest, and the product labels them that way.',
  'When ArmorIQ is not configured, enforcement runs as a local simulation that mirrors its rules. Every simulated decision is marked Simulated, and no latency is reported for it.',
  'Delivery of audit reports to ArmorIQ is best effort. The SDK does not raise when a report fails, so VeerIQ tracks each one and says so when delivery is unproven.',
  'Local development uses demo identities. Deployment supports OIDC; successful sign-in with a real provider still needs verification.',
  'The data is a synthetic fixture with one workflow. A second workflow needs its own adapter, and its rules are only as good as that adapter.',
  'A language model can behave differently on every run. The guarantees come from the layers around it, not from the model.',
]

export default function HowItWorks() {
  const status = useSystemStatus()

  return (
    <div className="space-y-10">
      <header className="max-w-3xl">
        <h1 className="text-3xl sm:text-4xl font-semibold leading-[1.05] tracking-[-0.03em] text-ink">
          An agent can repair data without being trusted with it
        </h1>
        <p className="mt-4 text-[16px] leading-relaxed text-ink-2">
          A person grants a narrow task. ArmorIQ signs the plan. Every request the agent makes then passes through five layers before it can touch the database, and each layer
          says no in its own way.
        </p>
        <div className="mt-3">
          {status.error && !status.data ? <ErrorState compact error={status.error} title="Current system status did not load" onRetry={() => void status.refetch()} /> : status.loading && !status.data ? <Skeleton className="h-6 w-56" /> : status.data ? <Badge tone={status.data.enforcement.simulated ? 'hold' : 'neutral'}>{status.data.enforcement.simulated ? 'Current system: simulated ArmorIQ' : 'Current system: live ArmorIQ'}</Badge> : <EmptyState title="Current mode unavailable" description="This diagram still explains the architecture; check System for connection status." />}
        </div>
      </header>

      <section aria-labelledby="flow-title">
        <h2 id="flow-title" className="sr-only">Follow one request through the gates</h2>
        <Panel strong>
          <FlowDiagram />
        </Panel>
      </section>

      <section aria-labelledby="who-title">
        <SectionHead id="who-title" title="Who enforces what">
          Four parties share the work. Naming each one’s limit keeps the claims honest.
        </SectionHead>
        <EnforcementTable />
      </section>

      <section aria-labelledby="story-title">
        <SectionHead id="story-title" title="The poisoned runbook, step by step">
          The flagship scenario. A note the agent should not trust asks it to undo a security decision.
        </SectionHead>
        <Story />
      </section>

      <section aria-labelledby="new-title">
        <SectionHead id="new-title" title="What is new, and what is not">
          Restoring data without old privileges is established practice. The contribution is narrower, and we would rather say so.
        </SectionHead>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)]">
          <Panel title="Already established" icon={<Info className="size-4" />}>
            <ul className="space-y-3">
              {EXISTING.map((t) => (
                <li key={t} className="text-[13px] leading-relaxed text-ink-2">
                  {t}
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="What VeerIQ adds" icon={<Check className="size-4" />} strong>
            <ul className="space-y-4">
              {CONTRIBUTIONS.map((c) => (
                <li key={c.title}>
                  <p className="text-[14px] font-semibold text-ink">{c.title}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-ink-3">{c.body}</p>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </section>

      <section aria-labelledby="limits-title">
        <SectionHead id="limits-title" title="Honest limitations" />
        <Disclosure summary={<span className="flex items-center gap-2"><TriangleAlert className="size-4" />What this does not claim</span>}>
          <ul className="grid gap-x-8 gap-y-3 lg:grid-cols-2">
            {LIMITS.map((t) => (
              <li key={t} className="flex gap-2.5 text-[13px] leading-relaxed text-ink-2">
                <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-[var(--outcome-hold)]" />
                {t}
              </li>
            ))}
          </ul>
        </Disclosure>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-line-strong bg-surface px-6 py-5">
        <div className="max-w-xl">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-ink">See it for real</h2>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-3">Run the flagship scenario, then check the proof board for the layer-by-layer evidence.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/">
            <Button variant="primary" iconRight={<ArrowRight className="size-4" />}>
              Go to Workspace
            </Button>
          </Link>
          <Link to="/proof">
            <Button variant="secondary">Open the proof board</Button>
          </Link>
        </div>
      </section>
    </div>
  )
}
