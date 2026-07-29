import { useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { LoginForm } from './components/LoginForm'
import { EmployeeDirectory } from './components/EmployeeDirectory'
import { ApprovalInbox } from './components/ApprovalInbox'
import { DashboardOverview } from './components/DashboardOverview'
import { WorkflowInstanceList } from './components/WorkflowInstanceList'

// Plain state-based view switching, not react-router-dom — this project's
// dashboard is a handful of admin-only screens behind one login, not an app
// that needs deep-linkable/bookmarkable URLs. Revisit if that ever becomes
// a real requirement (see docs/architecture for the tradeoff written up in
// full during Phase 12).
type View = 'home' | 'overview' | 'workflows'

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`border-b-2 px-3 py-2 text-sm font-medium ${
        active
          ? 'border-slate-900 text-slate-900'
          : 'border-transparent text-slate-500 hover:text-slate-700'
      }`}
    >
      {children}
    </button>
  )
}

function AuthenticatedView() {
  const { user, logout } = useAuth()
  const [view, setView] = useState<View>('home')
  if (!user) return null

  const isAdmin = user.role === 'administrator'

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="flex items-start justify-between rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Meridian Flow</h1>
            <p className="mt-1 text-sm text-slate-500">
              Enterprise Employee Workflow Automation Platform
            </p>
            <p className="mt-3 text-sm text-slate-700">
              Signed in as <span className="font-medium">{user.full_name}</span>
            </p>
            <p className="mt-1 text-xs text-slate-400">
              {user.email} · role: {user.role}
            </p>
          </div>
          <button
            onClick={logout}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
          >
            Sign out
          </button>
        </div>

        {isAdmin && (
          <nav className="mt-6 flex gap-1 border-b border-slate-200">
            <TabButton active={view === 'home'} onClick={() => setView('home')}>
              Home
            </TabButton>
            <TabButton active={view === 'overview'} onClick={() => setView('overview')}>
              Overview
            </TabButton>
            <TabButton active={view === 'workflows'} onClick={() => setView('workflows')}>
              Workflows
            </TabButton>
          </nav>
        )}

        <div className="mt-6">
          {view === 'overview' && isAdmin && <DashboardOverview />}

          {view === 'workflows' && isAdmin && <WorkflowInstanceList />}

          {view === 'home' && (
            <>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Pending Approvals
              </h2>
              <ApprovalInbox />

              <h2 className="mb-3 mt-6 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Employee Directory
              </h2>
              <EmployeeDirectory />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function AppShell() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <div className="min-h-screen bg-slate-50" />
  }

  return user ? <AuthenticatedView /> : <LoginForm />
}

function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}

export default App
