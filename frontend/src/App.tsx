import { useState } from 'react'
import {
  AlertTriangle,
  Bell,
  ClipboardCheck,
  Home,
  KeyRound,
  LayoutDashboard,
  LogOut,
  ScrollText,
  Users,
  Workflow,
} from 'lucide-react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { LoginForm } from './components/LoginForm'
import { EmployeeDirectory } from './components/EmployeeDirectory'
import { ApprovalInbox } from './components/ApprovalInbox'
import { DashboardOverview } from './components/DashboardOverview'
import { WorkflowInstanceList } from './components/WorkflowInstanceList'
import { WorkflowDetail } from './components/WorkflowDetail'
import { AuditLog } from './components/AuditLog'
import { AccessRequestForm } from './components/AccessRequestForm'
import { NotificationBell } from './components/NotificationBell'
import { NotificationsPanel } from './components/NotificationsPanel'
import { Avatar } from './components/ui/avatar'
import { Badge } from './components/ui/badge'
import { cn } from './lib/utils'

// Plain state-based view switching, not react-router-dom — this project's
// dashboard is a handful of admin-only screens behind one login, not an app
// that needs deep-linkable/bookmarkable URLs. Revisit if that ever becomes
// a real requirement (see docs/architecture for the tradeoff written up in
// full during Phase 12).
type View = 'home' | 'overview' | 'workflows' | 'failed' | 'workflow-detail' | 'audit-log'

// 'workflows' and 'failed' both open the same WorkflowDetail on row click —
// this remembers which list to return to on "Back" instead of hardcoding it.
type ListView = 'workflows' | 'failed'

const VIEW_TITLES: Record<View, string> = {
  home: 'Home',
  overview: 'Overview',
  workflows: 'Workflows',
  failed: 'Failed Workflows',
  'workflow-detail': 'Workflow Detail',
  'audit-log': 'Audit Log',
}

const VIEW_DESCRIPTIONS: Partial<Record<View, string>> = {
  home: 'Your notifications, approvals, and requests in one place.',
  overview: 'Platform-wide workflow health at a glance.',
  workflows: 'Every workflow instance across the company.',
  failed: 'Workflows that need manual attention.',
  'audit-log': 'A chronological record of everything the platform has done.',
}

const ROLE_LABELS: Record<string, string> = {
  employee: 'Employee',
  manager: 'Manager',
  hr: 'HR',
  it: 'IT',
  security: 'Security',
  administrator: 'Administrator',
}

function NavItem({
  active,
  onClick,
  icon: Icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors',
        active
          ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-sm'
          : 'text-sidebar-muted-foreground hover:bg-white/5 hover:text-sidebar-foreground',
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {children}
    </button>
  )
}

function SectionHeading({
  icon: Icon,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
      <Icon className="h-4 w-4 text-primary" />
      {children}
    </h2>
  )
}

function AuthenticatedView() {
  const { user, logout } = useAuth()
  const [view, setView] = useState<View>('home')
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null)
  const [detailOrigin, setDetailOrigin] = useState<ListView>('workflows')
  if (!user) return null

  const isAdmin = user.role === 'administrator'

  function openDetail(id: string, origin: ListView) {
    setSelectedInstanceId(id)
    setDetailOrigin(origin)
    setView('workflow-detail')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="flex h-screen w-64 shrink-0 flex-col overflow-y-auto bg-sidebar-background text-sidebar-foreground">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary font-bold text-primary-foreground">
            M
          </div>
          <div>
            <p className="text-sm font-semibold leading-tight">Meridian Flow</p>
            <p className="text-xs text-sidebar-muted-foreground">Cordant Industries</p>
          </div>
        </div>

        <div className="mx-5 border-t border-sidebar-border" />

        <nav className="flex flex-1 flex-col gap-1 p-3">
          <NavItem active={view === 'home'} onClick={() => setView('home')} icon={Home}>
            Home
          </NavItem>
          {isAdmin && (
            <>
              <NavItem
                active={view === 'overview'}
                onClick={() => setView('overview')}
                icon={LayoutDashboard}
              >
                Overview
              </NavItem>
              <NavItem
                active={view === 'workflows'}
                onClick={() => setView('workflows')}
                icon={Workflow}
              >
                Workflows
              </NavItem>
              <NavItem active={view === 'failed'} onClick={() => setView('failed')} icon={AlertTriangle}>
                Failed Workflows
              </NavItem>
              <NavItem
                active={view === 'audit-log'}
                onClick={() => setView('audit-log')}
                icon={ScrollText}
              >
                Audit Log
              </NavItem>
            </>
          )}
        </nav>

        <div className="mx-5 border-t border-sidebar-border" />

        <div className="p-3">
          <div className="flex items-center gap-2.5 rounded-md p-2">
            <Avatar name={user.full_name} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{user.full_name}</p>
              <p className="truncate text-xs text-sidebar-muted-foreground">{user.email}</p>
            </div>
          </div>
          <div className="px-2">
            <Badge
              variant="outline"
              className="border-sidebar-border text-sidebar-muted-foreground"
            >
              {ROLE_LABELS[user.role] ?? user.role}
            </Badge>
          </div>
          <button
            onClick={logout}
            className="mt-2 flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-sidebar-muted-foreground transition-colors hover:bg-white/5 hover:text-sidebar-foreground"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-card px-8 shadow-sm">
          <div>
            <h1 className="text-lg font-semibold leading-tight text-foreground">
              {view === 'workflow-detail' ? 'Workflow Detail' : VIEW_TITLES[view]}
            </h1>
            {VIEW_DESCRIPTIONS[view] && (
              <p className="text-xs text-muted-foreground">{VIEW_DESCRIPTIONS[view]}</p>
            )}
          </div>
          <NotificationBell onClick={() => setView('home')} />
        </header>

        <main className="flex-1 overflow-y-auto p-8">
          <div className="mx-auto max-w-6xl">
            {view === 'overview' && isAdmin && <DashboardOverview />}

            {view === 'workflows' && isAdmin && (
              <WorkflowInstanceList onSelectInstance={(id) => openDetail(id, 'workflows')} />
            )}

            {view === 'failed' && isAdmin && (
              <WorkflowInstanceList
                fixedStatus="failed"
                onSelectInstance={(id) => openDetail(id, 'failed')}
              />
            )}

            {view === 'workflow-detail' && isAdmin && selectedInstanceId && (
              <WorkflowDetail
                instanceId={selectedInstanceId}
                onBack={() => setView(detailOrigin)}
              />
            )}

            {view === 'audit-log' && isAdmin && <AuditLog />}

            {view === 'home' && (
              <div className="space-y-10">
                <section>
                  <SectionHeading icon={Bell}>Notifications</SectionHeading>
                  <NotificationsPanel />
                </section>

                <section>
                  <SectionHeading icon={ClipboardCheck}>Pending Approvals</SectionHeading>
                  <ApprovalInbox />
                </section>

                <section>
                  <SectionHeading icon={KeyRound}>Request Software Access</SectionHeading>
                  <AccessRequestForm />
                </section>

                <section>
                  <SectionHeading icon={Users}>Employee Directory</SectionHeading>
                  <EmployeeDirectory />
                </section>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

function AppShell() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <div className="min-h-screen bg-background" />
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
