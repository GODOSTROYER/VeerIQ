import type { Identity } from '@/api/types'

/**
 * Purpose-first labels for the local demo identities. A judge should read "what this
 * perspective is for" before the person's name.
 */
export interface Perspective {
  /** Short role label shown in place of the name. */
  label: string
  /** One line: why you would switch to this perspective. */
  purpose: string
}

export const OPERATOR_ID = 'maya'
export const APPROVER_ID = 'dev'
export const OTHER_TENANT_ID = 'sam'

const PERSPECTIVES: Record<string, Perspective> = {
  [OPERATOR_ID]: { label: 'Incident operator', purpose: 'Starts recovery runs and authorizes what the agent may touch.' },
  [APPROVER_ID]: { label: 'Approver', purpose: 'Signs off high-value repairs. Cannot approve a run they started.' },
  [OTHER_TENANT_ID]: { label: 'Other tenant', purpose: 'A different company on the same system. Proves it sees none of Atlas’s data.' },
}

export function perspective(identity: Pick<Identity, 'identity_id' | 'role'>): Perspective {
  return (
    PERSPECTIVES[identity.identity_id] ??
    (identity.role === 'reviewer'
      ? { label: 'Approver', purpose: 'Signs off high-value repairs.' }
      : { label: 'Operator', purpose: 'Starts recovery runs.' })
  )
}
