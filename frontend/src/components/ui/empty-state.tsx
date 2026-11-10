import type { ReactNode } from 'react'

import { Icon } from '@/components/icons'

type EmptyStateProps = { title: string; description: string; action?: ReactNode }

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-surface px-6 py-8 text-center">
      <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-background text-muted-foreground"><Icon name="info" /></span>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
