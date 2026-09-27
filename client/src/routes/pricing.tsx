import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { createCheckout, getPacks, ApiError, type Pack } from '../lib/api'
import { useSession } from '../lib/auth'
import { toast } from './__root'

export function PricingPage() {
  const { user, credits, refresh } = useSession()
  const [packs, setPacks] = useState<Record<string, Pack>>({})
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    getPacks().then(setPacks).catch(() => toast('Could not load packs'))
    refresh()
  }, [refresh])

  const buy = async (packId: string) => {
    if (!user) {
      toast('Log in first to buy credits')
      return
    }
    setBusy(packId)
    try {
      const { checkout_url } = await createCheckout(packId)
      window.location.href = checkout_url
    } catch (err) {
      toast((err as Error).message)
      if ((err as ApiError).status === 401) window.location.href = '/login'
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="min-h-screen bg-background px-4 sm:px-6 py-8 sm:py-12 max-w-4xl mx-auto">
      <div className="text-center mb-8">
        <h1 className="font-heading font-bold text-3xl">Buy credits</h1>
        <p className="text-zinc-500 mt-2">1 lead requested = 1 credit. Shortfalls refunded automatically.</p>
        {user && <p className="text-sm mt-2">Balance: <span className="font-semibold text-primary">{credits ?? '…'} credits</span></p>}
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {Object.entries(packs).map(([id, p]) => (
          <Card key={id}>
            <CardContent className="p-6 space-y-3">
              <h2 className="font-heading font-semibold text-xl">{p.credits} credits</h2>
              <p className="text-3xl font-bold">₦{Number(p.amount).toLocaleString()} <span className="text-sm font-normal text-zinc-400">{p.currency}</span></p>
              <p className="text-sm text-zinc-500">≈ {(Number(p.amount) / p.credits).toFixed(1)} per lead requested</p>
              <Button onClick={() => buy(id)} disabled={busy === id} className="w-full">
                {busy === id ? 'Redirecting to Bachs…' : 'Pay with Bachs'}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
      {!user && (
        <p className="text-center text-sm text-zinc-500 mt-6">
          <Link to="/login" className="text-primary font-medium">Log in</Link> to buy credits.
        </p>
      )}
      <p className="text-center text-xs text-zinc-400 mt-6">Cards, bank transfer, mobile money & crypto via Bachs. Fulfilled on payment webhook.</p>
    </div>
  )
}

export function SuccessPage() {
  const { refresh } = useSession()
  useEffect(() => {
    const t = setTimeout(refresh, 2000)
    return () => clearTimeout(t)
  }, [refresh])
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 sm:px-6">
      <Card className="max-w-sm w-full">
        <CardContent className="p-6 text-center space-y-3">
          <h1 className="font-heading font-bold text-xl">Payment received</h1>
          <p className="text-sm text-zinc-500">Your credits land as soon as Bachs confirms via webhook (usually seconds). Refresh your balance.</p>
          <Link to="/" className="inline-block px-4 py-2 rounded-xl bg-primary text-white text-sm font-medium">Back to search</Link>
        </CardContent>
      </Card>
    </div>
  )
}
