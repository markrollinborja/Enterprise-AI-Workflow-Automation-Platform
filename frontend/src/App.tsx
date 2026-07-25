import { AuthProvider, useAuth } from './context/AuthContext'
import { LoginForm } from './components/LoginForm'

function AuthenticatedView() {
  const { user, logout } = useAuth()
  if (!user) return null

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="max-w-md w-full rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Meridian Flow</h1>
        <p className="mt-1 text-sm text-slate-500">
          Enterprise Employee Workflow Automation Platform
        </p>

        <div className="mt-6 rounded-md border border-slate-200 p-4">
          <p className="text-sm text-slate-700">
            Signed in as <span className="font-medium">{user.full_name}</span>
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {user.email} · role: {user.role}
          </p>
        </div>

        <button
          onClick={logout}
          className="mt-4 w-full rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
        >
          Sign out
        </button>
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
