import { CaretRight as ChevronRightIcon } from '@phosphor-icons/react'
import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { SECOND_MS } from '@/lib/time'

const MINUTE_S = 60
const HOUR_S = 3600

function formatDuration(ms: number): string {
  const total = Math.max(1, Math.round(ms / SECOND_MS))
  if (total < MINUTE_S) return `${total}s`
  const hours = Math.floor(total / HOUR_S)
  const minutes = Math.floor((total % HOUR_S) / MINUTE_S)
  if (hours) return `${hours}h ${minutes}m`
  return `${minutes}m ${total % MINUTE_S}s`
}

export function Worked({
  ms,
  summary,
  children,
}: {
  ms: number | undefined
  summary: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="text-muted hover:text-fg hover:bg-raised -ml-2 flex max-w-full items-center gap-1.5 rounded-full px-2 py-1 text-left text-[12.5px]"
      >
        <span className="shrink-0">{ms ? `Worked for ${formatDuration(ms)}` : 'Worked'}</span>
        <ChevronRightIcon
          className={cn('text-faint size-3.5 shrink-0 transition-transform', open && 'rotate-90')}
        />
        {open || !summary ? null : <span className="text-faint min-w-0 truncate">{summary}</span>}
      </button>
      {open ? (
        <div className="border-line animate-fade-in mt-2 ml-1.5 space-y-4 border-l-2 pl-4">
          {children}
        </div>
      ) : null}
    </div>
  )
}
