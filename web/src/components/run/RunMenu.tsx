import {
  ArrowCounterClockwise,
  ArrowsInLineVertical,
  BellZ,
  CaretLeft,
  CaretRight,
  Checks,
  Clock,
  CopySimple,
  DotsThree,
  DownloadSimple,
  PushPin,
  PushPinSlash,
  SunHorizon,
  Trash,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '@shared/types.ts'
import { dialog } from '@/components/common/Dialog'
import { notify, reportError } from '@/components/common/Toasts'
import { MenuItem } from '@/components/common/MenuItem'
import { Button, IconButton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { useClickOutside } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { go, href } from '@/lib/route'
import { HOUR_MS, shortSpan, timeWithDay } from '@/lib/time'
import { cn } from '@/lib/cn'
import { refreshRuns, removeLocally, setPinned, setSettled, setSnoozed, WORKING } from '@/lib/runs'
import { BranchIcon, openThread } from './Branches'

const MORNING_HOUR = 9
const MONDAY = 1
const DAYS_IN_WEEK = 7
const MENU_WIDTH = 224
const SUBMENU_WIDTH = 248
const MENU_GAP = 6
const EDGE_PX = 8
const MORNING_TIME = `${String(MORNING_HOUR).padStart(2, '0')}:00`
const CALENDAR_CELLS = 6 * DAYS_IN_WEEK
const WEEKDAY_CHARS = 2
const WAITING_HINT = 'Answer first'

function at(days: number, hour: number): number {
  const when = new Date()
  when.setDate(when.getDate() + days)
  when.setHours(hour, 0, 0, 0)
  return when.getTime()
}

function nextMonday(): number {
  const ahead = (MONDAY - new Date().getDay() + DAYS_IN_WEEK) % DAYS_IN_WEEK || DAYS_IN_WEEK
  return at(ahead, MORNING_HOUR)
}

function startOfDay(when: Date): Date {
  return new Date(when.getFullYear(), when.getMonth(), when.getDate())
}

function monthStart(when: Date): Date {
  return new Date(when.getFullYear(), when.getMonth(), 1)
}

function monthGrid(month: Date): Date[] {
  const lead = (month.getDay() - MONDAY + DAYS_IN_WEEK) % DAYS_IN_WEEK
  return Array.from(
    { length: CALENDAR_CELLS },
    (_, i) => new Date(month.getFullYear(), month.getMonth(), 1 - lead + i),
  )
}

function withTime(day: Date, time: string): number {
  const [hours, minutes] = time.split(':').map(Number)
  const when = new Date(day)
  when.setHours(hours, minutes, 0, 0)
  return when.getTime()
}

function snoozeLabel(until: number): string {
  return timeWithDay(until, { weekday: 'short', day: 'numeric' })
}

function snoozePresets(): { label: string; until: number }[] {
  return [
    { label: 'In 1 hour', until: Date.now() + HOUR_MS },
    { label: 'In 3 hours', until: Date.now() + 3 * HOUR_MS },
    { label: 'Tomorrow', until: at(1, MORNING_HOUR) },
    { label: 'Next week', until: nextMonday() },
  ]
}

type RunAction = { label: string; icon: ReactNode; run: () => Promise<void> | void }

export function runActions(run: RunSummary, settled: boolean): RunAction[] {
  const actions: RunAction[] = [
    {
      label: run.pinned ? 'Unpin' : 'Pin to top',
      icon: run.pinned ? <PushPinSlash className="size-4" /> : <PushPin className="size-4" />,
      run: () => setPinned(run.id, !run.pinned),
    },
  ]

  const waiting = run.status === 'waiting'
  if (!settled && !waiting) {
    if (run.snoozedUntil)
      actions.push({
        label: 'Wake up now',
        icon: <SunHorizon className="size-4" />,
        run: () => setSnoozed(run.id, null),
      })

    for (const [index, preset] of snoozePresets().entries())
      actions.push({
        label: `Snooze: ${preset.label.toLowerCase()}`,
        icon: <BellZ className="size-4" />,
        run: () => setSnoozed(run.id, snoozePresets()[index].until),
      })
  }

  if (settled || !waiting)
    actions.push({
      label: settled ? 'Move back to active' : 'Settle',
      icon: settled ? <ArrowCounterClockwise className="size-4" /> : <Checks className="size-4" />,
      run: () => setSettled(run.id, !settled),
    })

  return actions
}

async function deleteThread(id: string, working: boolean): Promise<void> {
  const ok = await dialog.confirm({
    title: 'Delete this thread?',
    body: working
      ? 'It is still working, so it is stopped first. Its messages and files are removed for good.'
      : 'Its messages and files are removed for good.',
    confirmLabel: 'Delete',
    tone: 'danger',
  })
  if (!ok) return

  removeLocally(id)
  if (window.location.hash === href({ page: 'thread', id })) go({ page: 'home' })

  try {
    await api.deleteRun(id)
  } finally {
    await refreshRuns()
  }
}

function Calendar({ selected, onSelect }: { selected: Date; onSelect: (day: Date) => void }) {
  const [month, setMonth] = useState(() => monthStart(selected))
  const today = startOfDay(new Date())
  const days = monthGrid(month)
  const atFirstMonth = month.getTime() <= monthStart(today).getTime()

  const shift = (months: number) =>
    setMonth(new Date(month.getFullYear(), month.getMonth() + months, 1))

  return (
    <div>
      <div className="flex items-center justify-between pb-1">
        <IconButton
          label="Previous month"
          className="size-7"
          disabled={atFirstMonth}
          onClick={() => shift(-1)}
        >
          <CaretLeft className="size-3.5" />
        </IconButton>
        <span className="text-fg text-[12.5px] font-medium">
          {month.toLocaleDateString([], { month: 'long', year: 'numeric' })}
        </span>
        <IconButton label="Next month" className="size-7" onClick={() => shift(1)}>
          <CaretRight className="size-3.5" />
        </IconButton>
      </div>
      <div className="grid grid-cols-7">
        {days.slice(0, DAYS_IN_WEEK).map((day) => (
          <span
            key={day.getDay()}
            className="text-faint flex h-7 items-center justify-center text-[11px] font-medium"
          >
            {day.toLocaleDateString([], { weekday: 'short' }).slice(0, WEEKDAY_CHARS)}
          </span>
        ))}
        {days.map((day) => {
          const past = day < today
          const outside = day.getMonth() !== month.getMonth()
          const chosen = day.getTime() === selected.getTime()
          return (
            <button
              key={day.getTime()}
              type="button"
              disabled={past}
              aria-pressed={chosen}
              aria-label={day.toLocaleDateString([], { dateStyle: 'full' })}
              onClick={() => {
                onSelect(day)
                if (outside) setMonth(monthStart(day))
              }}
              className={cn(
                'relative mx-auto flex size-8 items-center justify-center rounded-full text-[12px] tabular-nums transition-colors',
                chosen
                  ? 'bg-brand text-on-brand font-medium'
                  : past
                    ? 'text-faint/70 cursor-not-allowed line-through'
                    : outside
                      ? 'text-faint hover:bg-raised'
                      : 'text-fg hover:bg-raised',
              )}
            >
              {day.getDate()}
              {day.getTime() === today.getTime() ? (
                <span
                  className={cn(
                    'absolute bottom-1 left-1/2 size-[3px] -translate-x-1/2 rounded-full',
                    chosen ? 'bg-on-brand' : 'bg-brand',
                  )}
                />
              ) : null}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function CustomSnooze({ onBack, onPick }: { onBack: () => void; onPick: (until: number) => void }) {
  const [day, setDay] = useState(() => startOfDay(new Date(at(1, MORNING_HOUR))))
  const [time, setTime] = useState(MORNING_TIME)
  const picked = withTime(day, time)
  const future = picked > Date.now()

  return (
    <div className="p-2">
      <Calendar selected={day} onSelect={setDay} />
      <div className="bg-line my-2 h-px" />
      <label className="flex items-center gap-2.5 px-1">
        <Clock className="text-muted size-4" />
        <span className="text-fg flex-1 text-[12.5px]">Time</span>
        <input
          type="time"
          required
          value={time}
          onChange={(e) => setTime(e.target.value)}
          className="border-line-strong focus:border-brand text-fg h-8 rounded-full border bg-white px-3 text-[12.5px] tabular-nums outline-none [&::-webkit-calendar-picker-indicator]:hidden"
        />
      </label>
      <div className={cn('px-1 pt-2 text-[11.5px]', future ? 'text-muted' : 'text-danger')}>
        {future
          ? `Wakes ${timeWithDay(picked, { weekday: 'short', month: 'short', day: 'numeric' })}`
          : 'Pick a time in the future'}
      </div>
      <div className="mt-2 flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button size="sm" variant="primary" disabled={!future} onClick={() => onPick(picked)}>
          Snooze
        </Button>
      </div>
    </div>
  )
}

function SnoozePanel({ onPick }: { onPick: (until: number) => void }) {
  const [custom, setCustom] = useState(false)
  if (custom) return <CustomSnooze onBack={() => setCustom(false)} onPick={onPick} />

  return (
    <div className="p-1.5">
      {snoozePresets().map((p) => (
        <MenuItem
          key={p.label}
          icon={<BellZ className="size-4" />}
          label={p.label}
          hint={snoozeLabel(p.until)}
          onClick={() => onPick(p.until)}
        />
      ))}
      <div className="bg-line mx-2 my-1 h-px" />
      <MenuItem
        icon={<BellZ className="size-4" />}
        label="Custom..."
        onClick={() => setCustom(true)}
      />
    </div>
  )
}

export function RunMenu({
  run,
  settled,
  inRow,
}: {
  run: RunSummary
  settled: boolean
  inRow?: boolean
}) {
  const [pos, setPos] = useState<{ left: number; top: number }>()
  const [snoozing, setSnoozing] = useState(false)
  const waiting = run.status === 'waiting'
  const [side, setSide] = useState<'right' | 'left'>('right')
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const submenu = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const node = submenu.current
    if (!node) return

    const fit = () => {
      node.style.translate = ''
      const overflow = node.getBoundingClientRect().bottom - window.innerHeight + EDGE_PX
      node.style.translate = overflow > 0 ? `0 ${-overflow}px` : ''
    }
    const observer = new ResizeObserver(fit)
    observer.observe(node)
    return () => observer.disconnect()
  }, [snoozing, waiting])

  const close = () => {
    setPos(undefined)
    setSnoozing(false)
  }

  useLayoutEffect(() => {
    if (!pos || !menu.current) return
    const box = menu.current.getBoundingClientRect()
    const top = Math.min(pos.top, window.innerHeight - box.height - EDGE_PX)
    const left = Math.min(Math.max(EDGE_PX, pos.left), window.innerWidth - box.width - EDGE_PX)
    if (top !== pos.top || left !== pos.left) setPos({ left, top })
    setSide(left + box.width + SUBMENU_WIDTH + EDGE_PX > window.innerWidth ? 'left' : 'right')
  }, [pos])

  useClickOutside([menu, trigger], close, Boolean(pos))

  useEffect(() => {
    if (!pos) return
    const onScroll = (e: Event) => !menu.current?.contains(e.target as Node) && close()
    document.addEventListener('scroll', onScroll, true)
    return () => document.removeEventListener('scroll', onScroll, true)
  }, [pos])

  useLayer(close, Boolean(pos))

  const act = (work: () => Promise<void> | void) => {
    close()
    void Promise.resolve(work()).catch(reportError)
  }

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="Thread actions"
        onClick={(e) => {
          e.stopPropagation()
          if (pos) return close()
          const box = e.currentTarget.getBoundingClientRect()
          setPos({ left: box.right - MENU_WIDTH, top: box.bottom + MENU_GAP })
        }}
        className={cn(
          'text-muted hover:text-fg flex shrink-0 items-center justify-center rounded-full transition-[color,background-color] hover:bg-black/[0.06]',
          inRow ? 'size-7' : 'size-8',
          inRow &&
            !pos &&
            'opacity-0 group-focus-within/run:opacity-100 group-hover/run:opacity-100',
          pos && 'bg-black/[0.06]',
        )}
      >
        <DotsThree weight="bold" className="size-4.5" />
      </button>
      {pos
        ? createPortal(
            <div
              ref={menu}
              role="menu"
              onClick={(e) => e.stopPropagation()}
              style={{ left: pos.left, top: pos.top, width: MENU_WIDTH }}
              className="border-line-strong/70 animate-pop fixed z-[200] rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
            >
              <MenuItem
                icon={
                  run.pinned ? <PushPinSlash className="size-4" /> : <PushPin className="size-4" />
                }
                label={run.pinned ? 'Unpin' : 'Pin to top'}
                onHover={() => setSnoozing(false)}
                onClick={() => act(() => setPinned(run.id, !run.pinned))}
              />
              {settled ? null : (
                <div className="relative">
                  <MenuItem
                    icon={<BellZ className="size-4" />}
                    label="Snooze"
                    active={snoozing}
                    disabled={waiting}
                    hint={waiting ? WAITING_HINT : undefined}
                    onHover={() => setSnoozing(!waiting)}
                    onClick={() => setSnoozing(true)}
                    trailing={waiting ? null : <CaretRight className="text-faint size-3.5" />}
                  />
                  {snoozing && !waiting ? (
                    <div
                      ref={submenu}
                      style={{ width: SUBMENU_WIDTH }}
                      className={cn(
                        'border-line-strong/70 animate-pop absolute -top-1.5 rounded-2xl border bg-white shadow-[var(--shadow-large)]',
                        side === 'right' ? 'left-full ml-2' : 'right-full mr-2',
                      )}
                    >
                      <SnoozePanel onPick={(until) => act(() => setSnoozed(run.id, until))} />
                    </div>
                  ) : null}
                </div>
              )}
              {run.snoozedUntil && !settled ? (
                <MenuItem
                  icon={<SunHorizon className="size-4" />}
                  label="Wake up now"
                  hint={`in ${shortSpan(run.snoozedUntil - Date.now())}`}
                  onHover={() => setSnoozing(false)}
                  onClick={() => act(() => setSnoozed(run.id, null))}
                />
              ) : null}
              {inRow ? null : (
                <MenuItem
                  icon={<ArrowsInLineVertical className="size-4" />}
                  label="Compact context"
                  disabled={WORKING.has(run.status)}
                  hint={WORKING.has(run.status) ? 'Working' : undefined}
                  onHover={() => setSnoozing(false)}
                  onClick={() =>
                    act(async () => {
                      await api.compactRun(run.id)
                    })
                  }
                />
              )}
              <MenuItem
                icon={<BranchIcon className="size-4" />}
                label="Branch"
                onHover={() => setSnoozing(false)}
                onClick={() => act(() => openThread(api.branch(run.id)))}
              />
              <div className="bg-line mx-2 my-1 h-px" />
              <MenuItem
                icon={<CopySimple className="size-4" />}
                label="Copy thread ID"
                onHover={() => setSnoozing(false)}
                onClick={() =>
                  act(async () => {
                    await navigator.clipboard.writeText(run.id)
                    notify(`Copied thread ID ${run.id}`)
                  })
                }
              />
              {inRow ? null : (
                <MenuItem
                  icon={<DownloadSimple className="size-4" />}
                  label="Export as Markdown"
                  onHover={() => setSnoozing(false)}
                  onClick={() => act(() => window.location.assign(api.exportUrl(run.id)))}
                />
              )}
              <div className="bg-line mx-2 my-1 h-px" />
              <MenuItem
                icon={
                  settled ? (
                    <ArrowCounterClockwise className="size-4" />
                  ) : (
                    <Checks className="size-4" />
                  )
                }
                label={settled ? 'Move back to active' : 'Settle'}
                disabled={!settled && waiting}
                hint={!settled && waiting ? WAITING_HINT : undefined}
                onHover={() => setSnoozing(false)}
                onClick={() => act(() => setSettled(run.id, !settled))}
              />
              <div className="bg-line mx-2 my-1 h-px" />
              <MenuItem
                icon={<Trash className="size-4" />}
                label="Delete thread"
                danger
                onHover={() => setSnoozing(false)}
                onClick={() => act(() => deleteThread(run.id, WORKING.has(run.status)))}
              />
            </div>,
            document.body,
          )
        : null}
    </>
  )
}

export function ParkedNotice({ run, settled }: { run: RunSummary; settled: boolean }) {
  const [busy, setBusy] = useState(false)

  const until = run.snoozedUntil
  const message = settled
    ? 'Settled. A new message moves it back to active.'
    : until
      ? `Snoozed until ${snoozeLabel(until)}. A new message wakes it up.`
      : undefined
  if (!message) return null

  const reopen = () => {
    setBusy(true)
    const done = settled ? setSettled(run.id, false) : setSnoozed(run.id, null)
    done.catch(reportError).finally(() => setBusy(false))
  }

  return (
    <div className="bg-brand-soft/60 text-text mb-2 flex items-center gap-3 rounded-2xl px-4 py-2.5 text-[12.5px]">
      {settled ? (
        <Checks className="text-brand size-4 shrink-0" />
      ) : (
        <BellZ className="text-brand size-4 shrink-0" />
      )}
      <span className="min-w-0 flex-1 leading-relaxed">{message}</span>
      <Button size="sm" className="shrink-0 gap-1.5" busy={busy} disabled={busy} onClick={reopen}>
        {settled ? (
          <ArrowCounterClockwise className="size-3.5" />
        ) : (
          <SunHorizon className="size-3.5" />
        )}
        {settled ? 'Move back to active' : 'Wake up now'}
      </Button>
    </div>
  )
}
