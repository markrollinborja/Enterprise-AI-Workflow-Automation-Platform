import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import { fetchAuthMode } from '../api/auth'
import { redirectToKeycloakLogin } from '../api/oidc'
import { API_BASE_URL } from '../api/client'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Input } from './ui/input'
import { Label } from './ui/label'

export function LoginForm() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isRedirecting, setIsRedirecting] = useState(false)
  // Defaults to 'local' while the /auth/mode call is in flight, rather
  // than flashing one form and swapping to the other a moment later. The
  // common case — a freshly cloned repo, AUTH_MODE unset — is local, so
  // that's the better default to render first.
  const [mode, setMode] = useState<'local' | 'oidc'>('local')

  useEffect(() => {
    fetchAuthMode()
      .then((response) => setMode(response.mode))
      .catch(() => setMode('local'))
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(email, password)
    } catch {
      setError('Incorrect email or password')
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleKeycloakSignIn() {
    setIsRedirecting(true)
    await redirectToKeycloakLogin()
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-sidebar-background p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary text-lg font-bold text-primary-foreground shadow-lg shadow-primary/30">
            M
          </div>
          <p className="mt-4 text-lg font-semibold text-sidebar-foreground">Meridian Flow</p>
          <p className="text-sm text-sidebar-muted-foreground">
            Enterprise Employee Workflow Automation
          </p>
        </div>

        <Card className="border-sidebar-border/50 shadow-xl">
          <CardContent className="pt-6">
            <p className="mb-4 text-sm font-medium text-foreground">Sign in to your account</p>

            {mode === 'oidc' ? (
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  This deployment authenticates through your organization's identity provider.
                </p>
                <Button
                  type="button"
                  onClick={handleKeycloakSignIn}
                  disabled={isRedirecting}
                  className="w-full"
                >
                  {isRedirecting ? 'Redirecting…' : 'Continue with Keycloak'}
                </Button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>

                {error && <p className="text-sm text-destructive">{error}</p>}

                <Button type="submit" disabled={isSubmitting} className="w-full">
                  {isSubmitting ? 'Signing in…' : 'Sign in'}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>

        {mode === 'local' && (
          <p className="mt-4 text-center text-xs text-sidebar-muted-foreground">
            Demo users: see backend/app/db/seed.py (e.g. ava.thompson@cordant.io, password from
            your local .env / seed script).
          </p>
        )}

        {/* Only shown in local mode — found live, not by inspection: the
            SAML PoC issues a local-mode token (ADR-0021), which
            get_current_user only accepts when AUTH_MODE=local
            (ADR-0015). The backend now refuses GET /auth/saml/login
            outright in oidc mode with a clear error, but offering a link
            here that a person in oidc mode would click into a 403 is
            worse than not offering it. A full page navigation, not a
            fetch: Keycloak's SAML SSO endpoint expects a browser-level
            redirect, the same way the Keycloak OIDC button above does. */}
        {mode === 'local' && (
          <p className="mt-3 text-center text-xs text-sidebar-muted-foreground">
            <a href={`${API_BASE_URL}/auth/saml/login`} className="underline hover:no-underline">
              Try the SAML PoC
            </a>
          </p>
        )}
      </div>
    </div>
  )
}
