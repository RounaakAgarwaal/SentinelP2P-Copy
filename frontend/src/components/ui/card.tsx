import type { HTMLAttributes } from 'react'

import { cn } from '@/utils/cn'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <section className={cn('rounded-lg border border-border bg-surface shadow-card', className)} {...props} />
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-1.5 p-5', className)} {...props} />
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-base font-semibold tracking-tight text-foreground', className)} {...props} />
}

export function CardDescription({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm leading-6 text-muted-foreground', className)} {...props} />
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 pb-5', className)} {...props} />
}

export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex items-center border-t border-border px-5 py-4', className)} {...props} />
}
