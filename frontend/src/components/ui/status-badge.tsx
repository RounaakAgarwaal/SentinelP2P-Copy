import type { HTMLAttributes } from 'react'

import { cn } from '@/utils/cn'

export type StatusTone = 'neutral' | 'sage' | 'warning' | 'critical' | 'accent'

const tones: Record<StatusTone, string> = {
  neutral: 'bg-background text-muted-foreground',
  sage: 'bg-sage/15 text-[#536b58]',
  warning: 'bg-warning/20 text-[#806829]',
  critical: 'bg-critical/15 text-[#9d5c49]',
  accent: 'bg-primary/12 text-[#995e3d]',
}

export function StatusBadge({ tone = 'neutral', className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: StatusTone }) {
  return <span className={cn('inline-flex min-h-6 items-center rounded-full px-2.5 text-xs font-medium', tones[tone], className)} {...props} />
}
