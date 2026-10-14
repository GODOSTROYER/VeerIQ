import { Fingerprint, ScanLine, UserCheck, UserRoundX } from 'lucide-react'

const POINTS = [
  { icon: UserRoundX, title: 'The requester cannot approve', body: 'Whoever starts the run cannot decide, even with the approver role.' },
  { icon: Fingerprint, title: 'One exact payload', body: 'The decision is bound to its digest. Change a single byte and approval no longer applies.' },
  { icon: ScanLine, title: 'The data is checked again', body: 'Approval never freezes data. The database re-checks holds, deletions and row versions before committing.' },
  { icon: UserCheck, title: 'Both systems must agree', body: 'VeerIQ asks for a second person on high-value repairs. If ArmorIQ also holds the action, both must approve.' },
]

export function SeparationOfDuties() {
  return <aside aria-labelledby="second-person-title" className="border-t border-line pt-5 lg:sticky lg:top-24 lg:border-t-0 lg:pt-0">
    <h2 id="second-person-title" className="text-base font-semibold tracking-[-0.02em] text-ink">Why a second person decides</h2>
    <p className="mt-2 text-xs text-ink-3">Separation of duties for high-value repairs.</p>
    <ul className="mt-5 space-y-5">{POINTS.map(({ icon: Icon, title, body }) => <li key={title} className="flex gap-2.5">
      <Icon className="mt-0.5 size-4 shrink-0 text-approval" aria-hidden />
      <div><p className="text-[13px] font-medium text-ink">{title}</p><p className="mt-1 text-[13px] leading-relaxed text-ink-2">{body}</p></div>
    </li>)}</ul>
  </aside>
}
