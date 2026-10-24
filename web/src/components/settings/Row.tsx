import type { ReactNode } from 'react'

export function Row({
  title,
  hint,
  children,
}: {
  title: string
  hint: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
      <div className="min-w-[240px] flex-1">
        <div className="text-fg text-[13.5px] font-medium">{title}</div>
        <div className="text-muted mt-0.5 text-[12px] leading-relaxed">{hint}</div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}
