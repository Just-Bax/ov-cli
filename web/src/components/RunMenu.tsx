import {
  ArrowCounterClockwise,
  BellZ,
  CaretRight,
  Checks,
  DotsThree,
  DownloadSimple,
  Eye,
  PushPin,
  PushPinSlash,
  SunHorizon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '@shared/types.ts'
import { reportError } from '@/components/Toasts'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import { useLayer } from '@/lib/layers'
import { cn } from '@/lib/cn'
import { setPinned, setSettled, setSnoozed } from '@/lib/runs'

const HOUR_MS = 3_600_000
const MORNING_HOUR = 9
const MONDAY = 1
const DAYS_IN_WEEK = 7
const MENU_WIDTH = 224
const SUBMENU_WIDTH = 248
const MENU_GAP = 6
const EDGE_PX = 8

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
  const d = new Date(ms - new Date(ms).getTimezoneOffset() * 60_000)
  return d.toISOString().slice(0, 16)
}

export function snoozeLabel(until: number): string {
  const when = new Date(until)
  const sameDay = when.toDateString() === new Date().toDateString()
  const time = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return sameDay
    ? time
    : `${when.toLocaleDateString([], { weekday: 'short', day: 'numeric' })}, ${time}`
}

function snoozePresets(): { label: string; until: number }[] {
  return [
    { label: 'In 1 hour', until: Date.now() + HOUR_MS },
    { label: 'In 3 hours', until: Date.now() + 3 * HOUR_MS },
    { label: 'Tomorrow', until: at(1, MORNING_HOUR) },
    { label: 'Next week', until: nextMonday() },
  ]
}

export type RunAction = { label: string; icon: ReactNode; run: () => Promise<void> | void }

export function runActions(run: RunSummary, settled: boolean): RunAction[] {
  const actions: RunAction[] = [
    {
      label: run.pinned ? 'Unpin' : 'Pin to top',
      icon: run.pinned ? <PushPinSlash className="size-4" /> : <PushPin className="size-4" />,
      run: () => setPinned(run.id, !run.pinned),
    },
  ]
  if (!settled) {
    if (run.snoozedUntil)
      actions.push({
        label: 'Wake up now',
        icon: <SunHorizon className="size-4" />,
        run: () => setSnoozed(run.id, null),
      })
    for (const preset of snoozePresets())
      actions.push({
        label: `Snooze: ${preset.label.toLowerCase()}`,
        icon: <BellZ className="size-4" />,
        run: () => setSnoozed(run.id, preset.until),
      })
  }
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
  trailing,
}: {
  icon: ReactNode
  label: string
  hint?: string
  onClick?: () => void
  onHover?: () => void
  active?: boolean
  trailing?: ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      onMouseEnter={onHover}
      className={cn(
        'flex h-8 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[12.5px] transition-colors',
        active ? 'bg-brand-soft text-brand-strong' : 'text-fg hover:bg-raised',
      )}
    >
      <span className={active ? 'text-brand-strong' : 'text-muted'}>{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint ? <span className="text-faint shrink-0 text-[11px]">{hint}</span> : null}
      {trailing}
    </button>
  )
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
  onWatch,
  inRow,
}: {
  run: RunSummary
  settled: boolean
  onWatch?: () => void
  inRow?: boolean
}) {
  const [pos, setPos] = useState<{ left: number; top: number }>()
  const [snoozing, setSnoozing] = useState(false)
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

  useEffect(() => {
    if (!pos) return
    const outside = (e: Event) => {
      if (!menu.current?.contains(e.target as Node) && !trigger.current?.contains(e.target as Node))
        close()
    }
    document.addEventListener('mousedown', outside)
    document.addEventListener('scroll', outside, true)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('scroll', outside, true)
    }
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
        title="More"
        onClick={(e) => {
          e.stopPropagation()
          if (pos) return close()
          const box = e.currentTarget.getBoundingClientRect()
          setPos({ left: box.right - MENU_WIDTH, top: box.bottom + MENU_GAP })
        }}
        className={cn(
          'text-muted hover:text-fg flex shrink-0 items-center justify-center rounded-full transition-[opacity,color,background-color] hover:bg-black/[0.06]',
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
                    onHover={() => setSnoozing(true)}
                    onClick={() => setSnoozing(true)}
                    trailing={<CaretRight className="text-faint size-3.5" />}
                  />
                  {snoozing ? (
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
                  hint={snoozeLabel(run.snoozedUntil)}
                  onHover={() => setSnoozing(false)}
                  onClick={() => act(() => setSnoozed(run.id, null))}
                />
              ) : null}
              {onWatch ? (
                <>
                  <div className="bg-line mx-2 my-1 h-px" />
                  <Item
                    icon={<Eye className="size-4" />}
                    label="Watch..."
                    onHover={() => setSnoozing(false)}
                    onClick={() => act(onWatch)}
                  />
                  <Item
                    icon={<DownloadSimple className="size-4" />}
                    label="Export as Markdown"
                    onHover={() => setSnoozing(false)}
                    onClick={() => act(() => window.location.assign(api.exportUrl(run.id)))}
                  />
                </>
              ) : null}
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
                onHover={() => setSnoozing(false)}
                onClick={() => act(() => setSettled(run.id, !settled))}
              />
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
