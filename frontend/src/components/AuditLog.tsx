import { useCallback, useEffect, useState } from 'react'
import { fetchAuditLog, type AuditTimelineEntryResponse } from '../api/dashboard'
import { useAuth } from '../context/AuthContext'
import { AuditTimelineList } from './AuditTimeline'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

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
        <p className="text-sm text-muted-foreground">
          Most recent activity across every workflow instance — see a specific instance's
          Workflow Detail page for its full timeline in order.
        </p>
        <Button variant="ghost" size="sm" onClick={load} className="text-muted-foreground">
          Refresh
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading audit log…</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {!isLoading && !error && (
        <Card>
          <CardContent className="pt-4">
            <AuditTimelineList entries={entries} showWorkflow />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
