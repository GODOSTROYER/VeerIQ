import { useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { api, errorMessage } from '@/api/client'
import { invalidate, TAGS } from '@/api/bus'
import { clearQueryCache } from '@/api/cache'
import { Button, Modal, Tooltip, useToast } from '@/components/ui'

/** Puts the disposable demo data back to the damaged starting point and refreshes every query. Throws on failure. */
export async function resetDemo(): Promise<{ generation: number }> {
  const res = await api.post<{ generation: number }>('/admin/reset')
  clearQueryCache()
  invalidate(TAGS.appState, TAGS.checks, TAGS.diff, TAGS.runs, TAGS.approvals, TAGS.metrics, TAGS.status)
  return res
}

/** Operator-only control: puts the disposable demo data back to the damaged starting point. */
export function ResetDemoButton() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const reset = async () => {
    setBusy(true)
    try {
      const res = await resetDemo()
      toast.success('Demo reset', `Fresh demo data is ready (generation ${res.generation}).`)
      setOpen(false)
    } catch (err) {
      toast.error('Reset failed', errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Tooltip content="Put the demo data back to the damaged starting point">
        <Button variant="ghost" size="sm" icon={<RotateCcw className="size-3.5" />} onClick={() => setOpen(true)}>
          Reset demo
        </Button>
      </Tooltip>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        dismissable={!busy}
        width="480px"
        title="Reset the demo?"
        description="This only touches the disposable demo data."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
              Keep current data
            </Button>
            <Button variant="danger" onClick={reset} loading={busy} data-autofocus>
              Reset demo data
            </Button>
          </div>
        }
      >
        <ul className="space-y-2.5 text-[13px] leading-snug text-ink-2">
          <li>The orders go back to their damaged state, with yesterday&rsquo;s deletions and revoked access still in place.</li>
          <li>Pending approvals and runs still in progress are cancelled.</li>
          <li>Finished runs and their evidence stay in the history.</li>
        </ul>
      </Modal>
    </>
  )
}
