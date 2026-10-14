import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError } from './client'
import { invalidate, TAGS } from './bus'
import { clearQueryCache } from './cache'
import type { Identity } from './types'

interface SessionValue {
  /** Signed-in demo identity, or null when nobody has chosen one yet. */
  authMode: 'demo' | 'oidc'
  identity: Identity | null
  /** True until the first GET /session answers. */
  loading: boolean
  /** Set when the backend cannot be reached. */
  error: Error | null
  identities: Identity[]
  signIn: (identityId: string) => Promise<void>
  signOut: () => Promise<void>
  reload: () => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [authMode, setAuthMode] = useState<'demo' | 'oidc'>('demo')
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [identities, setIdentities] = useState<Identity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const reload = useCallback(async () => {
    try {
      const config = await api.get<{mode:'demo'|'oidc'}>('/auth/config').catch((err:unknown) => { if(err instanceof ApiError && err.status===404) return {mode:'demo' as const};throw err })
      setAuthMode(config.mode)
      const [ids, me] = await Promise.all([
        api.get<Identity[]>('/identities').catch((err:unknown) => {if(err instanceof ApiError && err.status===401)return [];throw err}),
        api.get<Identity>('/session').catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 401) return null
          throw err
        }),
      ])
      setIdentities(ids)
      setIdentity(me)
      setError(null)
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const signIn = useCallback(async (identityId: string) => {
    const me = await api.post<Identity>('/session', { identity_id: identityId })
    clearQueryCache()
    setIdentity(me)
    invalidate(TAGS.appState, TAGS.checks, TAGS.diff, TAGS.runs, TAGS.approvals)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.post('/session/logout')
    } finally {
      clearQueryCache()
      setIdentity(null)
    }
  }, [])

  const value = useMemo<SessionValue>(
    () => ({ authMode, identity, loading, error, identities, signIn, signOut, reload }),
    [authMode, identity, loading, error, identities, signIn, signOut, reload],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>')
  return ctx
}

/** The list of local demo identities (GET /identities). */
export function useIdentities(): Identity[] {
  return useSession().identities
}
