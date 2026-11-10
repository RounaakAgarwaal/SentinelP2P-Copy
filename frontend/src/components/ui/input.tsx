import type { InputHTMLAttributes } from 'react'

import { cn } from '@/utils/cn'

export function Input({ className, type = 'text', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type={type} className={cn('h-10 w-full rounded-md border border-input bg-surface px-3 text-sm text-foreground placeholder:text-muted-foreground/75 focus-visible:border-primary disabled:cursor-not-allowed disabled:bg-background disabled:opacity-70', className)} {...props} />
}
