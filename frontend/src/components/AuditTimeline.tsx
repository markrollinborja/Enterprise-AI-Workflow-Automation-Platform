import type { AuditTimelineEntryResponse } from '../api/dashboard'
import { StatusBadge } from './WorkflowInstanceList'
import { Badge } from './ui/badge'

// Shared by the Workflow Detail page's per-instance timeline and the
// global Audit Log page (Phase 12d) — both render the exact same
// AuditTimelineEntryResponse shape from the same build_audit_timeline()
// backend function, just scoped differently (one instance vs. everything).
// One component instead of two near-identical renderers.

function formatDate(value: string): string {
  return new Date(value).toLocaleString()
}

const ACTOR_TYPE_VARIANT: Record<string, 'default' | 'muted' | 'warning'> = {
  user: 'default',
  ai: 'warning',
  system: 'muted',
}

function AuditTimelineRow({
  entry,
  showWorkflow,
}: {
  entry: AuditTimelineEntryResponse
  showWorkflow: boolean
}) {
  const metadataEntries = Object.entries(entry.metadata).filter(([, v]) => v !== null && v !== '')
  return (
    <li className="border-l-2 border-border py-1.5 pl-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground/70">{formatDate(entry.timestamp)}</span>
        <Badge variant={ACTOR_TYPE_VARIANT[entry.actor_type] ?? 'muted'}>{entry.actor}</Badge>
        <span className="text-sm text-foreground">{entry.action.replace(/_/g, ' ')}</span>
        <StatusBadge status={entry.outcome} />
        {showWorkflow && entry.workflow_name && (
          <span className="text-xs text-muted-foreground/70">— {entry.workflow_name}</span>
        )}
      </div>
      {metadataEntries.length > 0 && (
        <p className="mt-0.5 text-xs text-muted-foreground">
          {metadataEntries.map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}
        </p>
      )}
    </li>
  )
}

interface AuditTimelineListProps {
  entries: AuditTimelineEntryResponse[]
  /** The global Audit Log page mixes entries from every workflow instance,
   * so each row needs to say which workflow it belongs to — the per-
   * instance timeline on the Workflow Detail page already has that context
   * from the page itself, so it stays off there. */
  showWorkflow?: boolean
}

export function AuditTimelineList({ entries, showWorkflow = false }: AuditTimelineListProps) {
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No audit events yet.</p>
  }
  return (
    <ul className="space-y-1">
      {entries.map((entry, index) => (
        // No stable id on a synthesized timeline entry — index is fine,
        // this list is never reordered or filtered in place.
        <AuditTimelineRow key={index} entry={entry} showWorkflow={showWorkflow} />
      ))}
    </ul>
  )
}
