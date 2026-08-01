import { useEffect, useState } from 'react'
import { fetchApplications, type ApplicationResponse } from '../api/applications'
import { submitAccessRequest, type AccessRequestResponse } from '../api/access-requests'
import { useAuth } from '../context/AuthContext'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Label } from './ui/label'
import { Select } from './ui/select'
import { Textarea } from './ui/textarea'

const RISK_BADGE_VARIANT: Record<string, 'muted' | 'warning' | 'destructive'> = {
  low: 'muted',
  medium: 'warning',
  high: 'destructive',
}

export function AccessRequestForm() {
  const { token } = useAuth()
  const [applications, setApplications] = useState<ApplicationResponse[]>([])
  const [selectedAppId, setSelectedAppId] = useState('')
  const [justification, setJustification] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AccessRequestResponse | null>(null)

  useEffect(() => {
    if (!token) return
    fetchApplications(token)
      .then(setApplications)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load applications'))
      .finally(() => setIsLoading(false))
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !selectedAppId) return
    setError(null)
    setResult(null)
    setIsSubmitting(true)
    try {
      const response = await submitAccessRequest(token, selectedAppId, justification)
      setResult(response)
      setJustification('')
      setSelectedAppId('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit access request')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading applications…</p>
  }

  const selectedApp = applications.find((a) => a.id === selectedAppId)

  return (
    <Card>
      <CardContent className="pt-4">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="application">Application</Label>
            <Select
              id="application"
              required
              value={selectedAppId}
              onChange={(e) => setSelectedAppId(e.target.value)}
            >
              <option value="" disabled>
                Select an application
              </option>
              {applications.map((app) => (
                <option key={app.id} value={app.id}>
                  {app.name} ({app.risk_level})
                </option>
              ))}
            </Select>
          </div>

          {selectedApp && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant={RISK_BADGE_VARIANT[selectedApp.risk_level] ?? 'muted'}>
                {selectedApp.risk_level}
              </Badge>
              <span>{selectedApp.description}</span>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="justification">
              Justification (required for medium/high risk applications)
            </Label>
            <Textarea
              id="justification"
              rows={3}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="Why do you need access to this application?"
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          {result && (
            <div className="rounded-md bg-success/10 p-3 text-sm text-success">
              <p className="font-medium">Request submitted for {result.application_name}.</p>
              <p className="mt-1 text-xs">
                Risk: {result.computed_risk_level} · Status: {result.status}
                {result.auto_approved && ' · Auto-approved'}
              </p>
            </div>
          )}

          <Button type="submit" disabled={isSubmitting || !selectedAppId}>
            {isSubmitting ? 'Submitting…' : 'Submit Access Request'}
          </Button>
        </form>

        {applications.length === 0 && (
          <p className="mt-3 text-sm text-muted-foreground">No applications available to request.</p>
        )}
      </CardContent>
    </Card>
  )
}
