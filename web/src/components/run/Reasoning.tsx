import { CaretRight as ChevronRightIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import { cn } from '@/lib/cn'

export function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="text-muted hover:text-fg hover:bg-raised -ml-2 flex items-center gap-1.5 rounded-full px-2 py-1 text-[12.5px]"
      >
        Reasoning
        <ChevronRightIcon
          className={cn('text-faint size-3.5 transition-transform', open && 'rotate-90')}
        />
      </button>
      {open ? (
        <div className="border-line text-muted animate-fade-in mt-1 ml-1.5 border-l-2 pl-4 text-[12.5px] leading-relaxed [overflow-wrap:anywhere] whitespace-pre-wrap">
          {text.trim()}
        </div>
      ) : null}
    </div>
  )
}
