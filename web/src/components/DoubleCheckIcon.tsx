import { Checks } from '@phosphor-icons/react'
import { cn } from '@/lib/cn'

export function DoubleCheckIcon({ className }: { className?: string }) {
  return <Checks aria-hidden className={cn('size-4', className)} />
}
