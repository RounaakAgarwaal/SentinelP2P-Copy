import { useEffect, type ReactNode } from 'react'

import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'

type DialogProps = {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
}

export function Dialog({ open, onClose, title, description, children }: DialogProps) {
  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#302a24]/30 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section role="dialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby={description ? 'dialog-description' : undefined} className="w-full max-w-lg rounded-lg border border-border bg-surface shadow-dialog">
        <header className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <h2 id="dialog-title" className="text-lg font-semibold">{title}</h2>
            {description && <p id="dialog-description" className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>}
          </div>
          <Button variant="ghost" size="icon" aria-label="Close dialog" onClick={onClose}><Icon name="close" /></Button>
        </header>
        <div className="p-5">{children}</div>
      </section>
    </div>
  )
}
