import {
  BellSnoozeIcon,
  BookmarkIcon,
  EllipsisHorizontalIcon,
  SunIcon,
} from '@heroicons/react/24/outline'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '@shared/types.ts'
import { DoubleCheckIcon } from '@/components/DoubleCheckIcon'
import { reportError } from '@/components/Toasts'
import { cn } from '@/lib/cn'
import { setPinned, setSettled, setSnoozed } from '@/lib/runs'

const HOUR_MS = 3_600_000
const MORNING_HOUR = 9
const MONDAY = 1
const DAYS_IN_WEEK = 7
const MENU_WIDTH = 220
const MENU_GAP = 4

function tomorrowMorning(): number {
  const at = new Date()
  at.setDate(at.getDate() + 1)
  at.setHours(MORNING_HOUR, 0, 0, 0)
  return at.getTime()
}

function nextMonday(): number {
  const at = new Date()
  const ahead = (MONDAY - at.getDay() + DAYS_IN_WEEK) % DAYS_IN_WEEK || DAYS_IN_WEEK
  at.setDate(at.getDate() + ahead)
  at.setHours(MORNING_HOUR, 0, 0, 0)
  return at.getTime()
}

export function snoozeLabel(until: number): string {
  const at = new Date(until)
  const sameDay = at.toDateString() === new Date().toDateString()
  const time = at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return sameDay
    ? time
    : `${at.toLocaleDateString([], { weekday: 'short', day: 'numeric' })}, ${time}`
}

type Item = { label: string; icon: ReactNode; run: () => Promise<void> }

export function runActions(run: RunSummary, settled: boolean): Item[] {
  const items: Item[] = [
    {
      label: run.pinned ? 'Unpin' : 'Pin to top',
      icon: <BookmarkIcon className="size-4" />,
      run: () => setPinned(run.id, !run.pinned),
    },
  ]
  if (!settled) {
    if (run.snoozedUntil)
      items.push({
        label: 'Wake up now',
        icon: <SunIcon className="size-4" />,
        run: () => setSnoozed(run.id, null),
      })
    items.push(
      {
        label: 'Snooze 1 hour',
        icon: <BellSnoozeIcon className="size-4" />,
        run: () => setSnoozed(run.id, Date.now() + HOUR_MS),
      },
      {
        label: 'Snooze until tomorrow',
        icon: <BellSnoozeIcon className="size-4" />,
        run: () => setSnoozed(run.id, tomorrowMorning()),
      },
      {
        label: 'Snooze until Monday',
        icon: <BellSnoozeIcon className="size-4" />,
        run: () => setSnoozed(run.id, nextMonday()),
      },
    )
  }
  items.push({
    label: settled ? 'Move back to active' : 'Settle',
    icon: <DoubleCheckIcon className="size-4" />,
    run: () => setSettled(run.id, !settled),
  })
  return items
}

export function RunMenu({ run, settled }: { run: RunSummary; settled: boolean }) {
  const [at, setAt] = useState<{ left: number; top: number }>()
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!at || !menu.current) return
    const box = menu.current.getBoundingClientRect()
    if (box.bottom > window.innerHeight) setAt({ ...at, top: at.top - box.height - 40 })
  }, [at?.left])

  useEffect(() => {
    if (!at) return
    const close = (e: Event) => {
      if (!menu.current?.contains(e.target as Node) && !trigger.current?.contains(e.target as Node))
        setAt(undefined)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setAt(undefined)
    document.addEventListener('mousedown', close)
    document.addEventListener('scroll', close, true)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('scroll', close, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [at])

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="Thread actions"
        title="Pin, snooze or settle"
        onClick={(e) => {
          e.stopPropagation()
          if (at) return setAt(undefined)
          const box = e.currentTarget.getBoundingClientRect()
          setAt({ left: box.right - MENU_WIDTH, top: box.bottom + MENU_GAP })
        }}
        className={cn(
          'text-faint hover:text-brand-strong flex size-7 shrink-0 items-center justify-center rounded-full transition-[opacity,color,background-color] group-hover/run:opacity-100 hover:bg-black/[0.06] focus-visible:opacity-100',
          at ? 'bg-black/[0.06] opacity-100' : 'opacity-0',
        )}
      >
        <EllipsisHorizontalIcon className="size-4" />
      </button>
      {at
        ? createPortal(
            <div
              ref={menu}
              role="menu"
              onClick={(e) => e.stopPropagation()}
              style={{ left: at.left, top: at.top, width: MENU_WIDTH }}
              className="border-line-strong/70 animate-pop fixed z-[200] rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
            >
              {runActions(run, settled).map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setAt(undefined)
                    void item.run().catch(reportError)
                  }}
                  className="text-fg hover:bg-brand-soft hover:text-brand-strong flex h-8 w-full items-center gap-2.5 rounded-full px-3 text-left text-[12.5px]"
                >
                  <span className="text-muted">{item.icon}</span>
                  {item.label}
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
