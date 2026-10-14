import { Component, lazy, Suspense, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from 'react'
import { OPERATOR_ID } from '@/lib/roles'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { SessionProvider, useSession } from '@/api/session'
import { AppShell } from '@/components/shell/AppShell'
import { IdentityGate } from '@/components/shell/IdentityGate'
import { DetailProvider } from '@/lib/detail'
import { PageTransition } from '@/components/motion'
import { Button, EmptyState, ErrorState, Loader, Skeleton, ToastProvider } from '@/components/ui'
import MissionControl from '@/pages/MissionControl'

const RunWorkspace = lazy(() => import('@/pages/RunWorkspace'))
const Approvals = lazy(() => import('@/pages/Approvals'))
const ProofBoard = lazy(() => import('@/pages/ProofBoard'))
const HowItWorks = lazy(() => import('@/pages/HowItWorks'))
const ImportRecovery = lazy(() => import('@/pages/ImportRecovery'))
const JudgeWalkthrough = lazy(() => import('@/pages/JudgeWalkthrough'))

function PageFallback() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading page">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-40 w-full rounded-2xl" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-64 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    </div>
  )
}

/** Keeps one broken page from blanking the whole app. */
class PageBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null; key: string }> {
  state = { error: null as Error | null, key: this.props.resetKey }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  static getDerivedStateFromProps(props: { resetKey: string }, state: { key: string; error: Error | null }) {
    // Navigating to another page clears the error.
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page crashed', error, info.componentStack)
  }
  render() {
    if (this.state.error) {
      return <ErrorState title="This page hit an error" error={this.state.error} onRetry={() => this.setState({ error: null })} />
    }
    return this.props.children
  }
}

function NotFound() {
  return (
    <EmptyState
      icon={<Compass className="size-5" />}
      title="That page does not exist"
      description="The link may be old, or the run was removed when the demo was reset."
      action={
        <Link to="/">
          <Button variant="secondary">Back to Workspace</Button>
        </Link>
      }
    />
  )
}

function Splash() {
  return (
    <div className="grid min-h-screen place-items-center" role="status" aria-label="Loading VeerIQ">
      <div className="aurora" aria-hidden />
      <Loader size="lg" />
    </div>
  )
}

function Gate() {
  const { authMode, identity, identities, loading, error, reload, signIn } = useSession()
  const location = useLocation()
  // No upfront "who are you" screen: start as the incident operator. The perspective
  // switcher in the header (and the guided tour) change it when a step needs to.
  const [autoFailed, setAutoFailed] = useState(false)
  const tried = useRef(false)
  useEffect(() => {
    if (authMode === 'oidc' || loading || identity || error || tried.current) return
    const start = identities.find((i) => i.identity_id === OPERATOR_ID) ?? identities.find((i) => i.role === 'operator')
    if (!start) return
    tried.current = true
    signIn(start.identity_id).catch(() => setAutoFailed(true))
  }, [authMode, loading, identity, error, identities, signIn])

  if (loading || (!identity && !error && !autoFailed && identities.length > 0)) return <Splash />
  if (error && !identity) {
    return (
      <div className="grid min-h-screen place-items-center px-6">
        <div className="aurora" aria-hidden />
        <ErrorState error={error} title="VeerIQ cannot reach its backend" onRetry={() => void reload()} />
      </div>
    )
  }
  if (!identity && authMode === 'oidc') return <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-5 px-6"><h1 className="recovery-headline">Sign in to your recovery workspace.</h1><p className="text-ink-2">Your organization assigns your tenant and role. Operators start repairs; a separate reviewer approves designated changes.</p><a href="/api/auth/login" className="inline-flex min-h-12 w-fit items-center bg-primary px-6 font-medium text-ink-inverse hover:bg-[var(--primary-hover)]">Sign in with your organization</a></div>
  if (!identity) {
    return (
      <>
        <div className="aurora" aria-hidden />
        <IdentityGate />
      </>
    )
  }
  return (
    <AppShell>
      <PageTransition>
      <PageBoundary resetKey={location.pathname}>
        <Suspense fallback={<PageFallback />}>
          <Routes location={location}>
            <Route path="/" element={<MissionControl />} />
            <Route path="/runs/:runId" element={<RunWorkspace />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/proof" element={<ProofBoard />} />
            <Route path="/how" element={<HowItWorks />} />
            <Route path="/import" element={<ImportRecovery />} />
            <Route path="/walkthrough" element={<JudgeWalkthrough />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </PageBoundary>
      </PageTransition>
    </AppShell>
  )
}

export default function App() {
  return (
    <DetailProvider>
    <ToastProvider>
      <SessionProvider>
        <Gate />
      </SessionProvider>
    </ToastProvider>
    </DetailProvider>
  )
}
