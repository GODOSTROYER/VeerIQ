import { useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useSession } from '@/api/session'
import type { Identity } from '@/api/types'
import { tenantName } from '@/lib/labels'
import { Avatar, Badge, Loader, Skeleton, useToast } from '@/components/ui'
import { Wordmark } from './Logo'

const CAN_DO: Record<Identity['role'], { badge: string; copy: string }> = {
  operator: { badge: 'Operator', copy: 'Reviews grants, starts recovery runs and can reset the demo.' },
  reviewer: { badge: 'Second reviewer', copy: 'Approves or rejects high-value repairs. Cannot approve a run they started.' },
}
export function IdentityGate() {
  const { identities, signIn } = useSession()
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const choose = async (id: string) => {
    setBusy(id)
    try { await signIn(id) }
    catch (err) { toast.error('Could not sign in', errorMessage(err)); setBusy(null) }
  }
  return <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col justify-center px-6 py-16">
    <Wordmark linked={false} />
    <h1 className="mt-10 text-3xl font-semibold leading-tight text-ink">Choose your perspective</h1>
    <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-ink-2">VeerIQ repairs damaged data without undoing today&rsquo;s decisions. Different people hold different authority, so start by picking one.</p>
    <ul className="mt-8 overflow-hidden rounded-2xl border border-line bg-raised" aria-label="Local demo identities">
      {identities.length === 0 ? Array.from({ length: 3 }, (_, i) => <li key={i} className="p-5"><Skeleton className="h-20" /></li>) : identities.map((i) => <li key={i.identity_id} className="border-b border-line last:border-0">
        <button type="button" disabled={busy !== null} aria-busy={busy === i.identity_id || undefined} onClick={() => void choose(i.identity_id)}
          className="flex w-full items-start gap-4 p-5 text-left transition-colors hover:bg-surface-2 active:bg-surface-3 disabled:opacity-50">
          <Avatar name={i.name} color={i.color} size="lg" />
          <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><span className="text-base font-semibold">{i.name}</span><Badge>{CAN_DO[i.role].badge}</Badge></span>
            <span className="mt-1 block text-[13px] text-ink-2">{i.title} · {tenantName(i.tenant_id)}</span><span className="mt-2 block text-[13px] leading-relaxed text-ink-2">{CAN_DO[i.role].copy}</span>
            <span className="mt-2 inline-flex items-center gap-1.5 text-[13px] font-medium">{busy === i.identity_id ? 'Signing in' : 'Continue as ' + i.name.split(' ')[0]}{busy === i.identity_id ? <Loader size="sm" label="Signing in" /> : <ArrowRight className="size-3.5" aria-hidden />}</span>
          </span>
        </button>
      </li>)}
    </ul>
    <p className="mt-6 text-xs text-ink-3">Local demo identities. This build has no real accounts or passwords.</p>
  </main>
}
