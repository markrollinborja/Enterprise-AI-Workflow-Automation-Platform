import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { completeKeycloakLogin, OidcCallbackError } from '../api/oidc'
import { Card, CardContent } from './ui/card'

// Rendered when the browser lands on /auth/callback — the redirect target
// Keycloak sends the browser back to after login. Exchanges the
// authorization code for a token, hands it to AuthContext exactly the way
// a local-mode login does, then clears the code/state query params from
// the URL so a page refresh here can't attempt to redeem an already-used
// code.
export function OidcCallback() {
  const { loginWithToken } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    completeKeycloakLogin(window.location.search)
      .then((accessToken) => loginWithToken(accessToken))
      .then(() => {
        if (!cancelled) {
          window.history.replaceState({}, '', '/')
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(
          err instanceof OidcCallbackError ? err.message : 'Sign-in failed. Please try again.',
        )
      })

    return () => {
      cancelled = true
    }
    // Intentionally runs once: the code in the URL is single-use, so this
    // must not re-run on a loginWithToken identity change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sidebar-background p-4">
        <div className="w-full max-w-sm">
          <Card className="border-destructive/30 shadow-xl">
            <CardContent className="space-y-3 pt-6 text-center">
              <p className="text-sm font-medium text-destructive">{error}</p>
              <a href="/" className="inline-block text-sm text-primary underline">
                Back to sign in
              </a>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return <div className="min-h-screen bg-sidebar-background" />
}
