import { useEffect, useState } from 'react'

import AppShell from '@/layouts/AppShell'
import { getHealth } from '@/services/api'
import type { ApiConnectionState, HealthResponse } from '@/types/api'

export default function App() {
  const [apiState, setApiState] = useState<ApiConnectionState>('checking')
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

  return <AppShell apiState={apiState} apiMessage={health?.message} />
}
