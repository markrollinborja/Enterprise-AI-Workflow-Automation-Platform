// Drives the browser side of the authorization-code + PKCE flow against
// Keycloak directly — see ADR-0019 for why meridian-flow is a public
// client and this exchange happens here rather than through the backend.
// This is the one OIDC call the backend never sees: it has no secret to
// attach and no server-side session to create, so proxying it would only
// add a hop.

const OIDC_ISSUER = import.meta.env.VITE_OIDC_ISSUER ?? 'http://localhost:8080/realms/meridian'
const OIDC_CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'meridian-flow'
const OIDC_REDIRECT_URI =
  import.meta.env.VITE_OIDC_REDIRECT_URI ?? `${window.location.origin}/auth/callback`

// sessionStorage, not a React state variable or localStorage: this value
// only needs to survive one browser-initiated round trip away from the
// page and back (to Keycloak and back), never across tabs or after the
// login completes.
const VERIFIER_STORAGE_KEY = 'meridian_flow_oidc_verifier'
const STATE_STORAGE_KEY = 'meridian_flow_oidc_state'

function base64UrlEncode(bytes: ArrayBuffer): string {
  let binary = ''
  for (const byte of new Uint8Array(bytes)) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomUrlSafeString(byteLength: number): string {
  return base64UrlEncode(crypto.getRandomValues(new Uint8Array(byteLength)).buffer)
}

async function sha256Challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64UrlEncode(digest)
}

/**
 * Navigates the browser to Keycloak's hosted login page. Generates a PKCE
 * verifier (kept secret, in this tab, until the token exchange) and its
 * SHA-256 challenge (sent openly — that's the point of PKCE: the
 * challenge proves nothing on its own, only presenting the matching
 * verifier later does), plus a `state` value used purely to detect a
 * forged callback on return.
 */
export async function redirectToKeycloakLogin(): Promise<void> {
  const verifier = randomUrlSafeString(32)
  const state = randomUrlSafeString(16)
  sessionStorage.setItem(VERIFIER_STORAGE_KEY, verifier)
  sessionStorage.setItem(STATE_STORAGE_KEY, state)

  const challenge = await sha256Challenge(verifier)
  const params = new URLSearchParams({
    client_id: OIDC_CLIENT_ID,
    redirect_uri: OIDC_REDIRECT_URI,
    response_type: 'code',
    scope: 'openid',
    code_challenge: challenge,
    code_challenge_method: 'S256',
    state,
  })
  window.location.href = `${OIDC_ISSUER}/protocol/openid-connect/auth?${params.toString()}`
}

export class OidcCallbackError extends Error {}

/**
 * Completes the flow once Keycloak redirects back to /auth/callback.
 * Exchanges the authorization code for an access token and returns it —
 * the caller (OidcCallback) is responsible for handing that token to
 * AuthContext, the same way a local-mode token is.
 *
 * Validates `state` against what redirectToKeycloakLogin stored before
 * doing anything else. Without this, an attacker who obtains their own
 * valid authorization code could hand a victim a crafted callback URL and
 * have it silently redeemed and bound to the victim's session — the
 * standard OAuth CSRF defense for the redirect step, not a Meridian-
 * specific concern.
 */
export async function completeKeycloakLogin(search: string): Promise<string> {
  const params = new URLSearchParams(search)

  const oauthError = params.get('error')
  if (oauthError) {
    throw new OidcCallbackError(params.get('error_description') ?? oauthError)
  }

  const code = params.get('code')
  const returnedState = params.get('state')
  const expectedState = sessionStorage.getItem(STATE_STORAGE_KEY)
  const verifier = sessionStorage.getItem(VERIFIER_STORAGE_KEY)
  // Removed immediately, win or lose: a code is single-use and a verifier
  // tied to it is worthless afterward either way, and leaving them behind
  // would let a page refresh on this URL attempt a second, doomed
  // exchange with a stale code.
  sessionStorage.removeItem(VERIFIER_STORAGE_KEY)
  sessionStorage.removeItem(STATE_STORAGE_KEY)

  if (!code || !verifier || !returnedState || returnedState !== expectedState) {
    throw new OidcCallbackError('Sign-in could not be verified. Please try signing in again.')
  }

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: OIDC_CLIENT_ID,
    code,
    redirect_uri: OIDC_REDIRECT_URI,
    code_verifier: verifier,
  })

  const response = await fetch(`${OIDC_ISSUER}/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })
  if (!response.ok) {
    throw new OidcCallbackError('Keycloak rejected the sign-in request.')
  }

  const payload = (await response.json()) as { access_token?: string }
  if (!payload.access_token) {
    throw new OidcCallbackError('Keycloak did not return an access token.')
  }
  return payload.access_token
}
