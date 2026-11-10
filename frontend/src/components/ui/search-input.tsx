import type { InputHTMLAttributes } from 'react'

import { Icon } from '@/components/icons'
import { Input } from '@/components/ui/input'

export function SearchInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="relative w-full">
      <Icon name="search" size={17} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <Input {...props} type="search" className={`pl-9 ${props.className ?? ''}`} />
    </div>
  )
}
