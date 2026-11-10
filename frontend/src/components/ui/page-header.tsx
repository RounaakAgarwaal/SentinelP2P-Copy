import type { ReactNode } from 'react'

type PageHeaderProps = { eyebrow?: string; title: string; description?: string; actions?: ReactNode }

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        {eyebrow && <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[28px]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
