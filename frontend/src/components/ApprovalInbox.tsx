import { useCallback, useEffect, useState } from 'react'
import {
  decideApproval,
  fetchApprovals,
  type ApprovalDecision,
  type ApprovalRequestResponse,
} from '../api/approvals'
import { useAuth } from '../context/AuthContext'

export function ApprovalInbox() {
  const { token } = useAuth()
  const [approvals, setApprovals] = useState<ApprovalRequestResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notesByRequest, setNotesByRequest] = useState<Record<string, string>>({})
  const [decidingId, setDecidingId] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    fetchApprovals(token)
      .then(setApprovals)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load approvals'))
      .finally(() => setIsLoading(false))
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  async function handleDecision(approvalRequestId: string, decision: ApprovalDecision) {
    if (!token) return
    setDecidingId(approvalRequestId)
    setError(null)
    try {
      await decideApproval(token, approvalRequestId, decision, notesByRequest[approvalRequestId])
      // Decided items drop out of the inbox — refetch rather than splice
      // locally, since a decision can change what else is now pending
      // (e.g. approving manager_approval can immediately surface an
      // it_review_access request for a different approver, or none at all
      // if the AI didn't flag it).
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision')
    } finally {
      setDecidingId(null)
    }
  }

  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading approvals…</p>
  }

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }

  if (approvals.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-sm text-slate-500">Nothing waiting on you right now.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {approvals.map((approval) => (
        <div
          key={approval.id}
          className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-slate-900">
                {approval.workflow_name} — {approval.step_name}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {approval.employee_name ? `For ${approval.employee_name} · ` : ''}
                Requires: {approval.approver_role} · step {approval.sequence_order}
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Requested {new Date(approval.requested_at).toLocaleString()}
              </p>
            </div>
          </div>

          <input
            type="text"
            placeholder="Optional notes"
            value={notesByRequest[approval.id] ?? ''}
            onChange={(e) =>
              setNotesByRequest((prev) => ({ ...prev, [approval.id]: e.target.value }))
            }
            className="mt-3 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />

          <div className="mt-3 flex gap-2">
            <button
              onClick={() => handleDecision(approval.id, 'approved')}
              disabled={decidingId === approval.id}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Approve
            </button>
            <button
              onClick={() => handleDecision(approval.id, 'rejected')}
              disabled={decidingId === approval.id}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
