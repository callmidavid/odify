import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from '@tanstack/react-router'
import { Card, CardContent } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Button } from '../components/ui/button'
import { googleLogin, login, signup } from '../lib/api'
import { saveSession } from '../lib/auth'
import { toast } from './__root'

declare global {
  interface Window { google?: { accounts: { id: { initialize(o: unknown): void; renderButton(el: HTMLElement, o: unknown): void } } } }
}

const GOOGLE_CLIENT_ID = import.meta.env.ODIFY_GOOGLE_CLIENT_ID || ''

export function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [googleBusy, setGoogleBusy] = useState(false)
  const [gisReady, setGisReady] = useState(() => typeof window !== 'undefined' && !!window.google)
  const googleBoxRef = useRef<HTMLDivElement | null>(null)
  const googleBusyRef = useRef(false)

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return
    if (window.google) {
      setGisReady(true)
      return
    }
    let s = document.getElementById('google-gsi') as HTMLScriptElement | null
    if (!s) {
      s = document.createElement('script')
      s.id = 'google-gsi'
      s.src = 'https://accounts.google.com/gsi/client'
      s.async = true
      s.defer = true
      document.head.appendChild(s)
    }
    const onLoad = () => setGisReady(true)
    s.addEventListener('load', onLoad)
    if ((s as unknown as { loaded?: boolean }).loaded || window.google) setGisReady(true)
    return () => s?.removeEventListener('load', onLoad)
  }, [])

  useEffect(() => {
    const el = googleBoxRef.current
    if (!el || !GOOGLE_CLIENT_ID || !gisReady || !window.google) return
    el.innerHTML = ''
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: async (resp: { credential: string }) => {
        if (googleBusyRef.current) return
        googleBusyRef.current = true
        setGoogleBusy(true)
        try {
          const data = await googleLogin(resp.credential)
          saveSession(data.user, data.credits)
          toast(`Welcome — ${data.credits} credits`)
          nav({ to: '/' })
        } catch (err) {
          setError((err as Error).message)
          googleBusyRef.current = false
          setGoogleBusy(false)
        }
      },
    })
    window.google.accounts.id.renderButton(el, { theme: 'outline', size: 'large', width: 280 })
  }, [gisReady, nav])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const data = mode === 'login' ? await login(email.trim(), password) : await signup(email.trim(), password, name.trim())
      saveSession(data.user, data.credits)
      toast(`Welcome — ${data.credits} credits`)
      nav({ to: '/' })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 sm:px-6">
      <Card className="w-full max-w-sm">
        <CardContent className="p-6 space-y-4">
          <div className="text-center">
            <div className="w-8 h-8 rounded-lg gradient-primary inline-flex items-center justify-center text-white font-bold text-sm">O</div>
            <h1 className="font-heading font-bold text-xl mt-2">{mode === 'login' ? 'Log in' : 'Create account'}</h1>
            <p className="text-sm text-zinc-500 mt-1">New accounts start with 5 free credits. 1 lead requested = 1 credit.</p>
          </div>
          <form onSubmit={submit} className="space-y-3">
            {mode === 'signup' && (
              <Input label="Name" id="name" value={name} onChange={e => setName(e.target.value)} placeholder="Jane" />
            )}
            <Input label="Email" id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="you@example.com" />
            <Input label="Password" id="password" type="password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="Min 6 characters" />
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Sign up'}
            </Button>
          </form>
          {GOOGLE_CLIENT_ID ? (
            <div className={`flex flex-col items-center gap-2 transition-opacity ${googleBusy ? 'pointer-events-none opacity-60' : ''}`}>
              {!gisReady && (
                <div className="w-[280px] h-[40px] rounded-full bg-zinc-100 animate-pulse flex items-center justify-center text-xs text-zinc-400">
                  Loading Google sign-in…
                </div>
              )}
              <div ref={googleBoxRef} className="flex justify-center" />
            </div>
          ) : (
            <p className="text-xs text-zinc-400 text-center">Google sign-in needs ODIFY_GOOGLE_CLIENT_ID — email works now.</p>
          )}
          <p className="text-sm text-zinc-500 text-center">
            {mode === 'login' ? (
              <>No account? <Link to="/signup" className="text-primary font-medium">Sign up</Link></>
            ) : (
              <>Have an account? <Link to="/login" className="text-primary font-medium">Log in</Link></>
            )}
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

export function LoginPage() {
  return <AuthPage mode="login" />
}

export function SignupPage() {
  return <AuthPage mode="signup" />
}
