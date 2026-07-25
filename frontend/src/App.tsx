import { useEffect, useState } from 'react'
import { fetchHealth } from './api/client'

type ConnectionStatus = 'checking' | 'connected' | 'error'

function App() {
  const [status, setStatus] = useState<ConnectionStatus>('checking')

  useEffect(() => {
    fetchHealth()
      .then(() => setStatus('connected'))
      .catch(() => setStatus('error'))
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="max-w-md w-full rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Meridian Flow</h1>
        <p className="mt-1 text-sm text-slate-500">
          Enterprise Employee Workflow Automation Platform
        </p>

        <div className="mt-6 flex items-center gap-2 rounded-md border border-slate-200 p-3">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              status === 'connected'
                ? 'bg-emerald-500'
                : status === 'error'
                  ? 'bg-red-500'
                  : 'bg-amber-400'
            }`}
          />
          <span className="text-sm text-slate-700">
            {status === 'checking' && 'Checking backend connection…'}
            {status === 'connected' && 'Backend connected'}
            {status === 'error' && 'Backend unreachable — is the API running?'}
          </span>
        </div>
      </div>
    </div>
  )
}

export default App
