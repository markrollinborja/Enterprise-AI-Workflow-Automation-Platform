import { useEffect, useState } from 'react'
import { fetchApplications, type ApplicationResponse } from '../api/applications'
import { submitAccessRequest, type AccessRequestResponse } from '../api/access-requests'
import { useAuth } from '../context/AuthContext'

const RISK_STYLES: Record<string, string> = {
  low: 'bg-slate-100 text-slate-700',
  medium: 'bg-amber-100 text-amber-800',
  high: 'bg-red-100 text-red-800',
}

function RiskBadge({ label }: { label: string }) {
  const className = RISK_STYLES[label] ?? 'bg-slate-100 text-slate-700'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  )
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
    return <p className="text-sm text-slate-500">Loading applications…</p>
  }

  const selectedApp = applications.find((a) => a.id === selectedAppId)

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <form onSubmit={handleSubmit}>
        <div>
          <label className="block text-xs font-medium text-slate-600">Application</label>
          <select
            required
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
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
          </select>
        </div>

        {selectedApp && (
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <RiskBadge label={selectedApp.risk_level} />
            <span>{selectedApp.description}</span>
          </div>
        )}

        <div className="mt-3">
          <label className="block text-xs font-medium text-slate-600">
            Justification (required for medium/high risk applications)
          </label>
          <textarea
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            rows={3}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Why do you need access to this application?"
          />
        </div>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        {result && (
          <div className="mt-3 rounded-md bg-green-50 p-3 text-sm text-green-800">
            <p className="font-medium">Request submitted for {result.application_name}.</p>
            <p className="mt-1 text-xs">
              Risk: {result.computed_risk_level} · Status: {result.status}
              {result.auto_approved && ' · Auto-approved'}
            </p>
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !selectedAppId}
          className="mt-4 rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {isSubmitting ? 'Submitting…' : 'Submit Access Request'}
        </button>
      </form>

      {applications.length === 0 && (
        <p className="text-sm text-slate-500">No applications available to request.</p>
      )}
    </div>
  )
}
