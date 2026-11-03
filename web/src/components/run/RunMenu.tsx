import {
  ArrowBendDownRight,
  ArrowCounterClockwise,
  ArrowsInLineVertical,
  BellZ,
  CaretRight,
  Checks,
  CopySimple,
  DotsThree,
  DownloadSimple,
  PushPin,
  PushPinSlash,
  Sparkle,
  SunHorizon,
  Trash,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '@shared/types.ts'
import { dialog } from '@/components/common/Dialog'
import { notify, reportError, withProgress } from '@/components/common/Toasts'
import { Button } from '@/components/common/ui'
import { api } from '@/lib/api'
import { useClickOutside } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { go, href } from '@/lib/route'
import { HOUR_MS, MINUTE_MS, shortSpan, timeWithDay } from '@/lib/time'
import { cn } from '@/lib/cn'
import { refreshRuns, removeLocally, setPinned, setSettled, setSnoozed, WORKING } from '@/lib/runs'

const MORNING_HOUR = 9
const MONDAY = 1
const DAYS_IN_WEEK = 7
const MENU_WIDTH = 224
const SUBMENU_WIDTH = 248
const MENU_GAP = 6
const EDGE_PX = 8
const DATETIME_LOCAL_CHARS = 16
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

function localInput(ms: number): string {
  const d = new Date(ms - new Date(ms).getTimezoneOffset() * MINUTE_MS)
  return d.toISOString().slice(0, DATETIME_LOCAL_CHARS)
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

function Item({
  icon,
  label,
  hint,
  onClick,
  onHover,
  active,
  danger,
  disabled,
  trailing,
}: {
  icon: ReactNode
  label: string
  hint?: string
  onClick?: () => void
  onHover?: () => void
  active?: boolean
  danger?: boolean
  disabled?: boolean
  trailing?: ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={onHover}
      className={cn(
        'flex h-8 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        active
          ? 'bg-brand-soft text-brand-strong'
          : danger
            ? 'text-danger hover:bg-danger-soft'
            : 'text-fg enabled:hover:bg-raised',
      )}
    >
      <span className={active ? 'text-brand-strong' : danger ? 'text-danger' : 'text-muted'}>
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint ? <span className="text-faint shrink-0 text-[11px]">{hint}</span> : null}
      {trailing}
    </button>
  )
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

function SnoozePanel({ onPick }: { onPick: (until: number) => void }) {
  const [custom, setCustom] = useState(false)
  const [value, setValue] = useState(() => localInput(at(1, MORNING_HOUR)))
  const picked = new Date(value).getTime()

  if (custom)
    return (
      <div className="p-1.5">
        <div className="text-muted px-1 pb-1.5 text-[11.5px] font-medium">Snooze until</div>
        <input
          type="datetime-local"
          value={value}
          min={localInput(Date.now())}
          onChange={(e) => setValue(e.target.value)}
          className="border-line-strong focus:border-brand text-fg h-9 w-full rounded-xl border px-2.5 text-[12.5px] outline-none"
        />
        <div className="mt-2 flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setCustom(false)}>
            Back
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={!(picked > Date.now())}
            onClick={() => onPick(picked)}
          >
            Snooze
          </Button>
        </div>
      </div>
    )

  return (
    <div className="p-1.5">
      {snoozePresets().map((p) => (
        <Item
          key={p.label}
          icon={<BellZ className="size-4" />}
          label={p.label}
          hint={snoozeLabel(p.until)}
          onClick={() => onPick(p.until)}
        />
      ))}
      <div className="bg-line mx-2 my-1 h-px" />
      <Item icon={<BellZ className="size-4" />} label="Custom..." onClick={() => setCustom(true)} />
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
              <Item
                icon={
                  run.pinned ? <PushPinSlash className="size-4" /> : <PushPin className="size-4" />
                }
                label={run.pinned ? 'Unpin' : 'Pin to top'}
                onHover={() => setSnoozing(false)}
                onClick={() => act(() => setPinned(run.id, !run.pinned))}
              />
              {settled ? null : (
                <div className="relative">
                  <Item
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
                <Item
                  icon={<SunHorizon className="size-4" />}
                  label="Wake up now"
                  hint={`in ${shortSpan(run.snoozedUntil - Date.now())}`}
                  onHover={() => setSnoozing(false)}
                  onClick={() => act(() => setSnoozed(run.id, null))}
                />
              ) : null}
              <Item
                icon={<Sparkle className="size-4" />}
                label="Regenerate title"
                onHover={() => setSnoozing(false)}
                onClick={() =>
                  act(() =>
                    withProgress('Writing a new title', async () => {
                      await api.retitleRun(run.id)
                      await refreshRuns()
                    }),
                  )
                }
              />
              {inRow ? null : (
                <Item
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
              {inRow ? null : (
                <Item
                  icon={<ArrowBendDownRight className="size-4" />}
                  label="Continue in a new thread"
                  disabled={WORKING.has(run.status)}
                  hint={WORKING.has(run.status) ? 'Working' : undefined}
                  onHover={() => setSnoozing(false)}
                  onClick={() =>
                    act(() =>
                      withProgress('Summarizing this thread for the new one', async () => {
                        const { id } = await api.continueRun(run.id)
                        await refreshRuns()
                        go({ page: 'thread', id })
                      }),
                    )
                  }
                />
              )}
              <div className="bg-line mx-2 my-1 h-px" />
              <Item
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
                <>
                  <Item
                    icon={<DownloadSimple className="size-4" />}
                    label="Export as Markdown"
                    onHover={() => setSnoozing(false)}
                    onClick={() => act(() => window.location.assign(api.exportUrl(run.id)))}
                  />
                </>
              )}
              <div className="bg-line mx-2 my-1 h-px" />
              <Item
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
              <Item
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
