import { useCallback, useEffect, useState } from 'react'
import { fetchNotifications, markNotificationRead, type NotificationResponse } from '../api/notifications'
import { useAuth } from '../context/AuthContext'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { Separator } from './ui/separator'
import { cn } from '../lib/utils'

function timeAgo(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function NotificationsPanel() {
  const { token } = useAuth()
  const [notifications, setNotifications] = useState<NotificationResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    fetchNotifications(token)
      .then(setNotifications)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load notifications'))
      .finally(() => setIsLoading(false))
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  async function handleMarkRead(id: string) {
    if (!token) return
    try {
      const updated = await markNotificationRead(token, id)
      setNotifications((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } catch {
      // Non-critical — leave the notification as unread in the UI on failure.
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading notifications…</p>
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>
  }

  const unreadCount = notifications.filter((n) => !n.read_at).length

  return (
    <Card>
      <div className="flex items-center justify-between px-4 py-2.5">
        <span className="text-xs text-muted-foreground">
          {unreadCount} unread of {notifications.length}
        </span>
      </div>
      <Separator />
      <ul className="divide-y divide-border">
        {notifications.map((n) => (
          <li
            key={n.id}
            className={cn('flex items-start justify-between gap-3 px-4 py-3', !n.read_at && 'bg-accent/50')}
          >
            <div>
              <p className="text-sm font-medium text-foreground">{n.title}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{n.body}</p>
              <p className="mt-1 text-xs text-muted-foreground/70">{timeAgo(n.created_at)}</p>
            </div>
            {!n.read_at && (
              <Button variant="outline" size="sm" onClick={() => handleMarkRead(n.id)} className="shrink-0">
                Mark read
              </Button>
            )}
          </li>
        ))}
      </ul>
      {notifications.length === 0 && (
        <p className="p-4 text-sm text-muted-foreground">No notifications yet.</p>
      )}
    </Card>
  )
}
