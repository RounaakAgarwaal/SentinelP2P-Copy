import { useEffect, useState } from 'react'

import { getHealth } from '@/services/api'
import type { HealthResponse } from '@/types/api'

type ApiState = 'checking' | 'connected' | 'unavailable'

export default function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then((response) => {
        setHealth(response)
        setApiState('connected')
      })
      .catch(() => {
        if (!controller.signal.aborted) setApiState('unavailable')
      })
    return () => controller.abort()
  }, [])

  return (
    <main className="min-h-screen bg-background px-6 py-16 text-foreground">
      <section className="mx-auto max-w-3xl rounded-xl border bg-card p-8 shadow-sm">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Procurement intelligence
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">SentinelP2P</h1>
        <p className="mt-3 max-w-xl text-muted-foreground">
          React application foundation. The existing Streamlit research interface remains available separately.
        </p>
        <div className="mt-8 flex items-center gap-3 rounded-lg border p-4" aria-live="polite">
          <span className={`h-2.5 w-2.5 rounded-full ${apiState === 'connected' ? 'bg-emerald-500' : apiState === 'unavailable' ? 'bg-rose-500' : 'bg-amber-500'}`} />
          <div>
            <p className="font-medium">API {apiState}</p>
            <p className="text-sm text-muted-foreground">
              {health?.message ?? (apiState === 'checking' ? 'Checking the local FastAPI service…' : 'Start the FastAPI service to connect.')}
            </p>
          </div>
        </div>
      </section>
    </main>
  )
}
