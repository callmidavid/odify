import { useCallback, useEffect, useState } from 'react'
import { ApiError, getCredits, getToken, logout as apiLogout, type AuthUser } from './api'

export interface Session { user: AuthUser | null; credits: number | null }

function readUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem('odify_user')
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function saveSession(user: AuthUser, _credits: number) {
  localStorage.setItem('odify_user', JSON.stringify(user))
  window.dispatchEvent(new Event('odify-session'))
}

export function clearSession() {
  apiLogout()
  localStorage.removeItem('odify_user')
  window.dispatchEvent(new Event('odify-session'))
}

export function useSession() {
  const [session, setSession] = useState<Session>({ user: readUser(), credits: null })

  const refresh = useCallback(async () => {
    const user = readUser()
    if (!getToken() || !user) {
      setSession({ user: null, credits: null })
      return
    }
    setSession(s => ({ ...s, user }))
    try {
      const { credits } = await getCredits()
      setSession({ user, credits })
    } catch (err) {
      // Only drop the session when the backend rejects the token.
      // Network blips / cold starts / 5xx must NOT log the user out.
      if (err instanceof ApiError && err.status === 401) {
        clearSession()
        setSession({ user: null, credits: null })
      }
      // otherwise: keep existing session (user stays logged in)
    }
  }, [])

  useEffect(() => {
    refresh()
    const h = () => refresh()
    window.addEventListener('odify-session', h)
    return () => window.removeEventListener('odify-session', h)
  }, [refresh])

  return { ...session, refresh }
}
