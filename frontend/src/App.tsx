import { AuthProvider, useAuth } from './context/AuthContext'
import { LoginForm } from './components/LoginForm'
import { EmployeeDirectory } from './components/EmployeeDirectory'
import { ApprovalInbox } from './components/ApprovalInbox'

function AuthenticatedView() {
  const { user, logout } = useAuth()
  if (!user) return null

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-5xl px-6 py-8">
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

        <div className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Pending Approvals
          </h2>
          <ApprovalInbox />
        </div>

        <div className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Employee Directory
          </h2>
          <EmployeeDirectory />
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
