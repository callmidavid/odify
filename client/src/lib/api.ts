const BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

export interface PlaceLeadDTO {
  name: string
  phone: string
  address: string
  email: string
  website: string
}

export interface SearchPlacesResponse {
  session_id: string
  results: PlaceLeadDTO[]
  credits_charged?: number
  credits_refunded?: number
  credits_balance?: number
}

const TOKEN_KEY = 'odify_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}
function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

export class ApiError extends Error {
  status: number
  payload: unknown
  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.status = status
    this.payload = payload
  }
}

async function parseError(res: Response): Promise<never> {
  let payload: unknown = null
  let message = `Request failed (${res.status})`
  try {
    const text = await res.text()
    try {
      payload = JSON.parse(text)
      const d = (payload as { detail?: string })?.detail
      if (d) message = d
    } catch {
      if (text) message = text
    }
  } catch { /* ignore */ }
  throw new ApiError(message, res.status, payload)
}

export async function searchPlaces(
  niche: string,
  location: string,
  maxResults: number,
): Promise<SearchPlacesResponse> {
  const clamped = Math.max(1, Math.min(50, Math.floor(Number(maxResults) || 1)))
  const params = new URLSearchParams()
  params.set('niche', niche)
  params.set('location', location)
  params.set('max_results', String(clamped))
  const res = await fetch(`${BASE}/search-places`, {
    method: 'POST',
    body: params,
    headers: { ...authHeaders() },
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export interface AuthUser { id: string; email: string; name: string }
export interface AuthResponse { access_token: string; user: AuthUser; credits: number }

async function authPost(path: string, body: unknown): Promise<AuthResponse> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseError(res)
  const data = (await res.json()) as AuthResponse
  setToken(data.access_token)
  return data
}

export const signup = (email: string, password: string, name = '') => authPost('/auth/signup', { email, password, name })
export const login = (email: string, password: string) => authPost('/auth/login', { email, password })
export const googleLogin = (id_token: string) => authPost('/auth/google', { id_token })
export function logout() { setToken(null) }

export async function getCredits(): Promise<{ credits: number; email?: string }> {
  const res = await fetch(`${BASE}/me/credits`, { headers: { ...authHeaders() } })
  if (!res.ok) await parseError(res)
  return res.json()
}

export interface Pack { credits: number; amount: string; currency: string; label: string }
export async function getPacks(): Promise<Record<string, Pack>> {
  const res = await fetch(`${BASE}/billing/packs`)
  if (!res.ok) await parseError(res)
  return (await res.json()).packs
}

export async function createCheckout(pack_id: string): Promise<{ checkout_url: string; checkout_id: string }> {
  const res = await fetch(`${BASE}/billing/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ pack_id }),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export function csvUrl(sessionId: string) {
  return `${BASE}/download/csv/${sessionId}`
}

export function vcardUrl(sessionId: string, idx: number) {
  return `${BASE}/download/vcard/${sessionId}/${idx}`
}

export function allVcardsUrl(sessionId: string) {
  return `${BASE}/download/all-vcards/${sessionId}`
}
