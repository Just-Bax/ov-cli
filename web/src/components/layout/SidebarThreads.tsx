import { CaretUp as ChevronUpIcon } from '@phosphor-icons/react'
import { type RefObject, useEffect, useRef, useState } from 'react'
import type { RunList, RunSummary } from '@shared/types.ts'
import { Skeleton } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import type { Reveal } from '@/lib/motion'
import { showMoreSettled, sidebarOrder, WORKING } from '@/lib/runs'
import { DAY_MS } from '@/lib/time'
import { RunItem } from './SidebarRuns'

const RECENT_LIMIT = 40
const IN_PROGRESS = 'In progress'
const SHELF_PREVIEW = 5
const SHELF_STEP = 10
const SCROLL_EDGE_PX = 2
const CONTENT_INSET = 'px-[11px]'
const GROUP_GAP = 'mt-4'

function dayLabel(ts: number): string {
  const day = new Date(ts).setHours(0, 0, 0, 0)
  const today = new Date().setHours(0, 0, 0, 0)
  if (day === today) return 'Today'
  if (day === today - DAY_MS) return 'Yesterday'

  const sameYear = new Date(ts).getFullYear() === new Date().getFullYear()
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}

function group(runs: RunSummary[]): [string, RunSummary[]][] {
  const groups = new Map<string, RunSummary[]>()
  const pinned = runs.filter((r) => r.pinned)
  for (const r of runs.filter((x) => !x.pinned)) {
    const label = WORKING.has(r.status) ? IN_PROGRESS : dayLabel(r.updatedAt)
    groups.set(label, [...(groups.get(label) ?? []), r])
  }

  const active = groups.get(IN_PROGRESS)
  groups.delete(IN_PROGRESS)
  const rest: [string, RunSummary[]][] = active ? [[IN_PROGRESS, active], ...groups] : [...groups]
  return pinned.length ? [['Pinned', pinned], ...rest] : rest
}

function useScrollFades(ref: RefObject<HTMLDivElement | null>): string {
  const [edges, setEdges] = useState({ top: false, bottom: false })

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const measure = () =>
      setEdges({
        top: el.scrollTop > SCROLL_EDGE_PX,
        bottom: el.scrollTop + el.clientHeight < el.scrollHeight - SCROLL_EDGE_PX,
      })

    const resize = new ResizeObserver(measure)
    resize.observe(el)
    for (const child of el.children) resize.observe(child)
    el.addEventListener('scroll', measure, { passive: true })
    measure()

    return () => {
      resize.disconnect()
      el.removeEventListener('scroll', measure)
    }
  }, [ref])

  if (edges.top && edges.bottom) return 'fade-y'
  if (edges.top) return 'fade-top'
  return edges.bottom ? 'fade-bottom' : ''
}

function Shelf({
  label,
  runs,
  total,
  open,
  onToggle,
  onLoadMore,
  settled,
  isOpen,
}: {
  label: string
  runs: RunSummary[]
  total: number
  open: boolean
  onToggle: () => void
  onLoadMore?: () => Promise<void>
  settled?: boolean
  isOpen: (id: string) => boolean
}) {
  const [limit, setLimit] = useState(SHELF_PREVIEW)
  const visible = runs.slice(0, limit)
  const left = total - visible.length

  useEffect(() => {
    if (!open) setLimit(SHELF_PREVIEW)
  }, [open])

  const more = () => {
    const next = limit + SHELF_STEP
    setLimit(next)
    if (onLoadMore && next > runs.length && runs.length < total) void onLoadMore()
  }

  return (
    <section>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(
          'flex h-8 w-full items-center gap-2 text-[12px] font-medium transition-colors',
          CONTENT_INSET,
          open ? 'text-brand-strong' : 'text-faint hover:text-fg',
        )}
      >
        <span className="shrink-0">
          {label} <span className="tabular-nums">({total})</span>
        </span>
        <span className={cn('h-px flex-1', open ? 'bg-brand/30' : 'bg-line-strong/60')} />
        <ChevronUpIcon
          className={cn(
            'size-3 shrink-0 transition-transform duration-(--duration-small)',
            !open && 'rotate-180',
          )}
        />
      </button>
      {open ? (
        <div className="animate-fade-in mt-1 space-y-0.5">
          {visible.map((r) => (
            <RunItem key={r.id} run={r} active={isOpen(r.id)} settled={settled} />
          ))}
          {left > 0 ? (
            <button
              type="button"
              onClick={more}
              className={cn(
                'text-brand-strong hover:bg-canvas h-8 w-full rounded-full text-left text-[12px] font-medium',
                CONTENT_INSET,
              )}
            >
              Show more ({left} left)
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

export function SidebarThreads({
  list,
  showAll,
  snoozedOpen,
  settledOpen,
  reveal,
  isOpen,
  onShowAll,
  onToggleSnoozed,
  onToggleSettled,
}: {
  list?: RunList
  showAll: boolean
  snoozedOpen: boolean
  settledOpen: boolean
  reveal: (index: number) => Reveal
  isOpen: (id: string) => boolean
  onShowAll: () => void
  onToggleSnoozed: () => void
  onToggleSettled: () => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const fades = useScrollFades(scroller)
  const active = list?.active ?? []
  const settled = list?.settled ?? []
  const snoozed = list?.snoozed ?? []
  const settledTotal = list?.settledTotal ?? 0
  const ordered = sidebarOrder(active)
  const shown = showAll ? ordered : ordered.slice(0, RECENT_LIMIT)

  return (
    <div ref={scroller} className={cn('min-h-0 flex-1 overflow-y-auto', CONTENT_INSET, fades)}>
      <div className="flex min-h-full flex-col pt-2 pb-3">
        {!list ? (
          <div className={cn('space-y-4 pt-3', CONTENT_INSET)}>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
            ))}
          </div>
        ) : null}
        {group(shown).map(([label, members], index) => (
          <div key={label} className={index ? GROUP_GAP : undefined}>
            <div className={cn('text-faint mb-1 text-[12px] font-medium', CONTENT_INSET)}>
              {label}
            </div>
            <div className="space-y-0.5">
              {members.map((r) => (
                <RunItem
                  key={r.id}
                  run={r}
                  active={isOpen(r.id)}
                  reveal={reveal(shown.indexOf(r))}
                />
              ))}
            </div>
          </div>
        ))}
        {!showAll && active.length > RECENT_LIMIT ? (
          <button
            type="button"
            onClick={onShowAll}
            className={cn(
              'text-brand-strong hover:bg-canvas mt-1 h-9 w-full rounded-full text-left text-[12.5px] font-medium',
              CONTENT_INSET,
            )}
          >
            Show all {active.length} threads
          </button>
        ) : null}
        {list && !active.length ? (
          <div className={cn('text-faint py-3 text-[12.5px]', CONTENT_INSET)}>
            {settledTotal
              ? 'Everything is settled. Start a new thread with a case number or a question.'
              : 'Your threads appear here. Start one with a case number or a question.'}
          </div>
        ) : null}
        {snoozed.length || settledTotal ? (
          <div className="mt-auto space-y-1 pt-4">
            {snoozed.length ? (
              <Shelf
                label="Snoozed"
                runs={snoozed}
                total={snoozed.length}
                open={snoozedOpen}
                onToggle={onToggleSnoozed}
                isOpen={isOpen}
              />
            ) : null}
            {settledTotal ? (
              <Shelf
                label="Settled"
                runs={settled}
                total={settledTotal}
                open={settledOpen}
                onToggle={onToggleSettled}
                onLoadMore={showMoreSettled}
                settled
                isOpen={isOpen}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
