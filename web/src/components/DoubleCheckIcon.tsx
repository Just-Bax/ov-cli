import { cn } from '@/lib/cn'

export function DoubleCheckIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-slot="icon"
      className={cn('size-4', className)}
    >
      <path d="M2.5 12.5 7 17 17.5 6.5" />
      <path d="M11.5 15.5 13 17 23.5 6.5" />
    </svg>
  )
}
