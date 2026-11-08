import { type ReactNode, useState } from 'react'
import { createPortal } from 'react-dom'

const TIP_GAP_PX = 10

type TipAt = { x: number; y: number }

export type RailTipHandle = ReturnType<typeof useRailTip>

export function useRailTip() {
  const [at, setAt] = useState<TipAt>()

  return {
    at,
    show: (e: React.MouseEvent<HTMLElement>) => {
      const box = e.currentTarget.getBoundingClientRect()
      setAt({ x: box.right + TIP_GAP_PX, y: box.top + box.height / 2 })
    },
    hide: () => setAt(undefined),
  }
}

export function RailTip({ at, children }: { at?: TipAt; children: ReactNode }) {
  if (!at) return null

  return createPortal(
    <div
      role="tooltip"
      className="animate-tip border-line-strong/70 text-fg pointer-events-none fixed z-[60] flex max-w-[260px] -translate-y-1/2 flex-col rounded-xl border bg-white px-3 py-1.5 text-[12.5px] leading-snug font-medium shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
      style={{ left: at.x, top: at.y }}
    >
      <span className="border-line-strong/70 absolute top-1/2 -left-[5px] size-2.5 -translate-y-1/2 rotate-45 border-b border-l bg-white" />
      {children}
    </div>,
    document.body,
  )
}
