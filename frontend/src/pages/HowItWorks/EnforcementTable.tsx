import type { ReactNode } from 'react'
import { Cog, Database, Layers, ShieldCheck } from 'lucide-react'
import { Panel } from '@/components/ui'
import { tint } from '@/lib/color'
import { Technical } from '@/lib/detail'

interface Row {
  who: string
  where: string
  color: string
  icon: ReactNode
  plain: string
  enforces: string[]
  limits: string
}

const ROWS: Row[] = [
  {
    who: 'ArmorIQ',
    plain: 'Stops tools outside the signed plan and checks organization policy.',
    where: 'External service and SDK',
    color: 'var(--layer-armoriq)',
    icon: <ShieldCheck className="size-4" />,
    enforces: [
      'A signed intent plan for each task',
      'Tool-level plan binding: a tool outside the plan is refused',
      'Organization policy: allow, block or hold',
      'Approvals for held actions',
    ],
    limits: 'The SDK path used here binds the tool name, not argument values. Argument checks are done by VeerIQ.',
  },
  {
    who: 'VeerIQ runtime',
    plain: 'Keeps the original grant fixed, binds approvals to the exact repair, and makes retries safe.',
    where: 'Generic authority layer',
    color: 'var(--layer-runtime)',
    icon: <Cog className="size-4" />,
    enforces: [
      'The original grant is preserved across replans and cannot be widened',
      'Approvals bound to the exact payload digest',
      'Idempotency: a retry returns the first receipt',
      'Events and evidence for every decision',
    ],
    limits: 'It knows nothing about orders. It trusts the adapter for what counts as correct data.',
  },
  {
    who: 'VeerIQ adapter',
    plain: 'Uses approved snapshot values while preserving deletions, holds and later edits.',
    where: 'Order repair workflow',
    color: 'var(--layer-domain)',
    icon: <Layers className="size-4" />,
    enforces: [
      'Values derived from the approved snapshot, never from the agent',
      'Tombstones: deleted records stay deleted',
      'Holds and newer edits are respected',
      'Tenant and field scope, and row versions',
    ],
    limits: 'It prepares exact manifests. It never writes to the database itself.',
  },
  {
    who: 'PostgreSQL',
    plain: 'Restricts writable columns and commits the repair in one checked transaction.',
    where: 'The database',
    color: 'var(--layer-postgres)',
    icon: <Database className="size-4" />,
    enforces: [
      'Column privileges for the limited executor role',
      'Single-transaction locking and re-checks at commit',
      'Immutable snapshots and manifests',
    ],
    limits: 'It enforces privileges and consistency, not whether a repair is a good idea.',
  },
]

/** Four enforcers, what each one is responsible for, and where its responsibility ends. */
export function EnforcementTable() {
  return (
    <Panel flush>
      <table className="block w-full border-collapse text-left md:table">
        <caption className="sr-only">Who enforces what in VeerIQ</caption>
        <thead className="hidden md:table-header-group">
          <tr className="border-b border-line text-xs text-ink-3">
            <th scope="col" className="w-[22%] px-5 py-3 font-medium">Who</th>
            <th scope="col" className="px-5 py-3 font-medium">What it protects</th>
            <th scope="col" className="w-[28%] px-5 py-3 font-medium">Its limit</th>
          </tr>
        </thead>
        <tbody className="block md:table-row-group">
          {ROWS.map((r) => (
            <tr key={r.who} className="block border-b border-line last:border-b-0 md:table-row">
              <th scope="row" className="block px-5 pb-1 pt-4 text-left align-top md:table-cell md:py-4">
                <span className="flex items-center gap-2.5">
                  <span className="grid size-8 place-items-center rounded-lg" style={{ background: tint(r.color, 15), color: r.color }}>
                    {r.icon}
                  </span>
                  <span>
                    <span className="block text-[14px] font-semibold text-ink">{r.who}</span>
                    <span className="block text-xs font-normal text-ink-3">{r.where}</span>
                  </span>
                </span>
              </th>
              <td className="block px-5 py-2 align-top md:table-cell md:py-4">
                <p className="text-[14px] leading-relaxed text-ink-2">{r.plain}</p>
                <Technical><ul className="mt-3 space-y-1.5">
                  {r.enforces.map((e) => (
                    <li key={e} className="flex gap-2 text-[13px] leading-snug text-ink-2">
                      <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full" style={{ background: r.color }} />
                      {e}
                    </li>
                  ))}
                </ul></Technical>
              </td>
              <td className="block px-5 pb-4 pt-1 align-top text-[13px] leading-snug text-ink-3 md:table-cell md:py-4">{r.limits}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
