import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchCurrentUser, login as loginRequest, type CurrentUser } from '../api/auth'

// localStorage is fine here — this is real application code running in the
// user's own browser, not a Claude artifact preview (which has different,
// stricter storage constraints).
const TOKEN_STORAGE_KEY = 'meridian_flow_token'

interface AuthContextValue {
  user: CurrentUser | null
  token: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  loginWithToken: (accessToken: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY)
    if (!storedToken) {
      setIsLoading(false)
      return
    }
    fetchCurrentUser(storedToken)
      .then((currentUser) => {
        setUser(currentUser)
        setToken(storedToken)
      })
      .catch(() => localStorage.removeItem(TOKEN_STORAGE_KEY))
      .finally(() => setIsLoading(false))
  }, [])

  async function login(email: string, password: string) {
    const { access_token: accessToken } = await loginRequest({ email, password })
    await loginWithToken(accessToken)
  }

  // Shared by local-mode login (after POST /auth/login) and OIDC login
  // (after OidcCallback exchanges a code for a token) — from this point on
  // a bearer token is a bearer token, and app/api/deps.py already made
  // that true on the backend side (ADR-0015). Neither caller needs to
  // know which mode produced it.
  async function loginWithToken(accessToken: string) {
    const currentUser = await fetchCurrentUser(accessToken)
    localStorage.setItem(TOKEN_STORAGE_KEY, accessToken)
    setUser(currentUser)
    setToken(accessToken)
  }

  function logout() {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setUser(null)
    setToken(null)
  }

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, loginWithToken, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
