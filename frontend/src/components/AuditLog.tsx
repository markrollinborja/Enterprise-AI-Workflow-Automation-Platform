import { useCallback, useEffect, useState } from 'react'
import { fetchAuditLog, type AuditTimelineEntryResponse } from '../api/dashboard'
import { useAuth } from '../context/AuthContext'
import { AuditTimelineList } from './AuditTimeline'

export function AuditLog() {
  const { token } = useAuth()
  const [entries, setEntries] = useState<AuditTimelineEntryResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    fetchAuditLog(token)
      .then(setEntries)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load audit log'))
      .finally(() => setIsLoading(false))
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          Most recent activity across every workflow instance — see a specific instance's
          Workflow Detail page for its full timeline in order.
        </p>
        <button onClick={load} className="text-xs text-slate-500 underline">
          Refresh
        </button>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading audit log…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!isLoading && !error && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <AuditTimelineList entries={entries} showWorkflow />
        </div>
      )}
    </div>
  )
}
