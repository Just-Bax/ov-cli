import {
  Alarm as AlarmIcon,
  Bell as BellIcon,
  BellZ as SnoozedIcon,
  Check as CheckIcon,
  CircleNotch as SpinnerIcon,
  WarningCircle as WarningCircleIcon,
} from '@phosphor-icons/react'
import { useEffect, useRef } from 'react'
import type { Attention, RunSummary } from '@shared/types.ts'
import { EditableTitle } from '@/components/common/EditableTitle'
import { type Icon, PulseDot } from '@/components/common/ui'
import { RunMenu } from '@/components/run/RunMenu'
import { RUN_STATUS, StatusIcon } from '@/components/run/RunStatus'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import type { Reveal } from '@/lib/motion'
import { go, href } from '@/lib/route'
import { refreshRuns } from '@/lib/runs'
import { shortSpan } from '@/lib/time'
import { prefetchRun } from '@/lib/useRun'
import { RailTip, useRailTip } from './RailTip'

const BUSY = new Set(['queued', 'running'])
const HOVER_PREFETCH_MS = 150
const INITIALS_CHARS = 2
const ROW_INSET = 'pr-[11px] pl-[11px]'

type Signal = { label: string; icon: Icon; tone: string }

const WORKING_SIGNAL: Signal = {
  label: 'Working',
  icon: SpinnerIcon,
  tone: 'text-brand animate-spin',
}
const NEEDS_YOU: Signal = { label: 'Needs you', icon: BellIcon, tone: 'text-warn' }
const SNOOZED: Signal = { label: 'Snoozed', icon: SnoozedIcon, tone: 'text-brand' }
const ATTENTION: Record<Attention, Signal> = {
  woke: { label: 'Woke', icon: AlarmIcon, tone: 'text-woke' },
  done: { label: 'Done', icon: CheckIcon, tone: 'text-ok' },
  failed: { label: 'Failed', icon: WarningCircleIcon, tone: 'text-danger' },
}

function runSignal(run: RunSummary, open: boolean): Signal | undefined {
  if (BUSY.has(run.status)) return WORKING_SIGNAL
  if (run.status === 'waiting') return NEEDS_YOU
  if (!open && run.attention) return ATTENTION[run.attention]
  return run.snoozedUntil ? SNOOZED : undefined
}

function RunSignal({ run, open }: { run: RunSummary; open: boolean }) {
  const signal = runSignal(run, open)
  if (!signal || signal === SNOOZED) {
    const until = BUSY.has(run.status) ? undefined : run.snoozedUntil
    return (
      <span
        className={cn(
          'text-[11.5px] font-normal tabular-nums',
          until ? 'text-brand' : 'text-faint',
        )}
      >
        {until ? shortSpan(until - Date.now()) : shortSpan(Date.now() - run.updatedAt)}
      </span>
    )
  }

  return (
    <signal.icon
      weight="bold"
      role="img"
      aria-label={signal.label}
      className={cn('size-3.5', signal.tone)}
    />
  )
}

function useHoverPrefetch(id: string, active: boolean) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => () => clearTimeout(timer.current), [])

  return {
    start: () => {
      if (active) return
      clearTimeout(timer.current)
      timer.current = setTimeout(() => prefetchRun(id), HOVER_PREFETCH_MS)
    },
    stop: () => clearTimeout(timer.current),
  }
}

export function RunItem({
  run,
  active,
  settled,
  reveal,
}: {
  run: RunSummary
  active: boolean
  settled?: boolean
  reveal?: Reveal
}) {
  const hover = useHoverPrefetch(run.id, active)

  return (
    <div
      role="link"
      tabIndex={0}
      onMouseEnter={hover.start}
      onMouseLeave={hover.stop}
      onClick={() => go({ page: 'thread', id: run.id })}
      onKeyDown={(e) => e.key === 'Enter' && go({ page: 'thread', id: run.id })}
      title={run.title}
      style={reveal?.style}
      className={cn(
        reveal?.className,
        'group/run relative flex h-9 cursor-pointer items-center gap-1.5 rounded-full text-[12.5px] font-medium transition-colors outline-none',
        ROW_INSET,
        active
          ? 'bg-brand-soft text-brand-strong'
          : settled
            ? 'text-muted hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas'
            : 'text-text hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas',
      )}
    >
      <EditableTitle
        value={run.title}
        onSave={async (title) => {
          await api.renameRun(run.id, title)
          await refreshRuns()
        }}
        className="min-w-0 flex-1 truncate"
        inputClassName="h-7 text-[12.5px] font-medium"
      />
      <span className="relative -mr-1.5 flex h-7 min-w-7 shrink-0 items-center justify-end">
        <span className="flex items-center pr-1 group-focus-within/run:invisible group-hover/run:invisible">
          <RunSignal run={run} open={active} />
        </span>
        <span className="absolute inset-0 flex items-center justify-center">
          <RunMenu run={run} settled={Boolean(settled)} inRow />
        </span>
      </span>
    </div>
  )
}

function initials(title: string): string {
  const words = title.split(/[^A-Za-z0-9]+/).filter((w) => w && !/^\d+$/.test(w))

  const letters =
    words
      .slice(0, INITIALS_CHARS)
      .map((w) => w[0])
      .join('') || title.trim().slice(0, INITIALS_CHARS)

  return letters.toUpperCase() || '#'
}

export function RailRun({
  run,
  active,
  reveal,
}: {
  run: RunSummary
  active: boolean
  reveal?: Reveal
}) {
  const tip = useRailTip()
  const hover = useHoverPrefetch(run.id, active)
  const busy = BUSY.has(run.status)
  const signal = runSignal(run, active)

  return (
    <a
      href={href({ page: 'thread', id: run.id })}
      aria-label={run.title}
      onMouseEnter={(e) => {
        tip.show(e)
        hover.start()
      }}
      onMouseLeave={() => {
        tip.hide()
        hover.stop()
      }}
      style={reveal?.style}
      className={cn(
        reveal?.className,
        'group/rail relative mx-auto flex size-9 items-center justify-center',
      )}
    >
      <span
        className={cn(
          'flex size-7 items-center justify-center rounded-full text-[10.5px] font-semibold tracking-tight transition-colors',
          active
            ? 'bg-brand text-white'
            : 'bg-raised text-text group-hover/rail:bg-brand-soft group-hover/rail:text-brand-strong',
        )}
      >
        {initials(run.title)}
      </span>
      {busy || signal ? (
        <span className="absolute right-0 bottom-0 flex size-3.5 items-center justify-center rounded-full bg-white">
          {busy ? (
            <PulseDot className="size-2" />
          ) : signal ? (
            <signal.icon weight="bold" className={cn('size-2.5', signal.tone)} />
          ) : null}
        </span>
      ) : null}
      <RailTip at={tip.at}>
        <span className="line-clamp-2">{run.title}</span>
        <span className="text-muted mt-0.5 flex items-center gap-1.5 text-[11.5px] font-normal">
          <StatusIcon status={run.status} className="size-3" />
          {RUN_STATUS[run.status].text}
        </span>
      </RailTip>
    </a>
  )
}
