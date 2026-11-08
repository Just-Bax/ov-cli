import { BellZ as SnoozedIcon, Checks as DoubleCheckIcon } from '@phosphor-icons/react'
import type { RunList } from '@shared/types.ts'
import { cn } from '@/lib/cn'
import type { Reveal } from '@/lib/motion'
import { RailTip, useRailTip } from './RailTip'
import { RailRun } from './SidebarRuns'

const RAIL_RUNS = 12
const SHELF_BUTTON =
  'text-faint hover:bg-canvas relative flex h-8 w-14 items-center justify-center gap-1 rounded-full text-[11px] font-medium tabular-nums transition-colors'

export function RailThreads({
  list,
  reveal,
  isOpen,
  onShowAll,
  onOpenSnoozed,
  onOpenSettled,
}: {
  list?: RunList
  reveal: (index: number) => Reveal
  isOpen: (id: string) => boolean
  onShowAll: () => void
  onOpenSnoozed: () => void
  onOpenSettled: () => void
}) {
  const moreTip = useRailTip()
  const settledTip = useRailTip()
  const snoozedTip = useRailTip()
  const active = list?.active ?? []
  const snoozed = list?.snoozed ?? []
  const settledTotal = list?.settledTotal ?? 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-line-strong/60 mt-1 min-h-0 flex-1 scrollbar-thin space-y-0.5 overflow-y-auto border-t px-2 pt-3 pb-3">
        {active.slice(0, RAIL_RUNS).map((r, i) => (
          <RailRun key={r.id} run={r} active={isOpen(r.id)} reveal={reveal(i)} />
        ))}
        {active.length > RAIL_RUNS ? (
          <button
            type="button"
            onClick={onShowAll}
            onMouseEnter={moreTip.show}
            onMouseLeave={moreTip.hide}
            className="text-faint hover:text-brand-strong hover:bg-canvas relative mx-auto flex size-9 items-center justify-center rounded-full text-[11px] font-medium"
          >
            +{active.length - RAIL_RUNS}
            <RailTip at={moreTip.at}>Show all threads</RailTip>
          </button>
        ) : null}
      </div>
      {snoozed.length || settledTotal ? (
        <div className="flex shrink-0 flex-col items-center gap-0.5 pb-2">
          {snoozed.length ? (
            <button
              type="button"
              onClick={onOpenSnoozed}
              onMouseEnter={snoozedTip.show}
              onMouseLeave={snoozedTip.hide}
              className={cn(SHELF_BUTTON, 'hover:text-brand-strong')}
            >
              <SnoozedIcon aria-hidden className="size-3.5" />
              {snoozed.length}
              <RailTip at={snoozedTip.at}>Snoozed threads</RailTip>
            </button>
          ) : null}
          {settledTotal ? (
            <button
              type="button"
              onClick={onOpenSettled}
              onMouseEnter={settledTip.show}
              onMouseLeave={settledTip.hide}
              className={cn(SHELF_BUTTON, 'hover:text-ok')}
            >
              <DoubleCheckIcon aria-hidden className="size-3.5" />
              {settledTotal}
              <RailTip at={settledTip.at}>Settled threads</RailTip>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
