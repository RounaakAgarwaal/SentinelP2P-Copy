import type { SelectHTMLAttributes } from 'react'

import { Icon } from '@/components/icons'
import { cn } from '@/utils/cn'

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select className={cn('h-10 w-full appearance-none rounded-md border border-input bg-surface pl-3 pr-9 text-sm text-foreground focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-60', className)} {...props}>
        {children}
      </select>
      <Icon name="chevron-down" size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
    </div>
  )
}
