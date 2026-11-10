import type { HTMLAttributes, ThHTMLAttributes, TdHTMLAttributes } from 'react'

import { cn } from '@/utils/cn'

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return <div className="w-full overflow-x-auto"><table className={cn('w-full caption-bottom text-sm', className)} {...props} /></div>
}
export function TableHeader({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn('[&_tr]:border-b [&_tr]:border-border', className)} {...props} />
}
export function TableBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}
export function TableRow({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn('border-b border-border transition-colors hover:bg-background/70', className)} {...props} />
}
export function TableHead({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn('h-11 px-4 text-left align-middle text-xs font-medium text-muted-foreground', className)} {...props} />
}
export function TableCell({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-4 py-3 align-middle text-sm text-foreground', className)} {...props} />
}
