import { ArrowsInLineVertical as CompactIcon } from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import type { Compaction, ContextUsage } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button, Shimmer } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatTokens } from '@/lib/cost'
import { useClickOutside } from '@/lib/hooks'

const RING_RADIUS = 6
const RING_SIZE = 16
const RING_STROKE = 2
const RING_LENGTH = 2 * Math.PI * RING_RADIUS
const WARN_SHARE = 0.75
const PERCENT = 100

function share(context: ContextUsage): number {
  return Math.min(1, context.tokens / (context.compactAt ?? context.limit))
}

function Ring({ value, warn }: { value: number; warn: boolean }) {
  return (
    <svg
      width={RING_SIZE}
      height={RING_SIZE}
      viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
      className="-rotate-90"
    >
      <circle
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={RING_RADIUS}
        fill="none"
        strokeWidth={RING_STROKE}
        className="stroke-line-strong"
      />
      <circle
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={RING_RADIUS}
        fill="none"
        strokeWidth={RING_STROKE}
        strokeLinecap="round"
        strokeDasharray={RING_LENGTH}
        strokeDashoffset={RING_LENGTH * (1 - value)}
        className={cn('transition-[stroke-dashoffset]', warn ? 'stroke-warn' : 'stroke-brand')}
      />
    </svg>
  )
}

export function ContextMeter({
  runId,
  context,
  busy,
}: {
  runId: string
  context: ContextUsage
  busy: boolean
}) {
  const [open, setOpen] = useState(false)
  const [asking, setAsking] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  useClickOutside([trigger, panel], () => setOpen(false), open)

  const used = share(context)
  const warn = used >= WARN_SHARE
  const percent = Math.round(used * PERCENT)

  const compact = () => {
    setAsking(true)
    api
      .compactRun(runId)
      .then(() => setOpen(false), reportError)
      .finally(() => setAsking(false))
  }

  return (
    <div className="relative shrink-0">
      <button
        ref={trigger}
        type="button"
        aria-label="Context window"
        aria-expanded={open}
        title={`Context ${percent}% full`}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        className={cn(
          'hover:bg-raised inline-flex h-8 items-center gap-1.5 rounded-full px-2 text-[12px] font-medium tabular-nums transition-colors',
          warn ? 'text-warn' : 'text-muted',
        )}
      >
        <Ring value={used} warn={warn} />
        {percent}%
      </button>
      {open ? (
        <div
          ref={panel}
          className="border-line-strong/70 animate-pop absolute bottom-full left-0 z-[200] mb-2 w-[260px] rounded-2xl border bg-white p-3.5 text-[12px] shadow-[var(--shadow-large)]"
        >
          <div className="text-fg flex items-baseline justify-between font-semibold">
            <span>Context</span>
            <span className="tabular-nums">{percent}%</span>
          </div>
          <div className="text-muted mt-1 leading-relaxed">
            {formatTokens(context.tokens)} of {formatTokens(context.limit)} tokens in use.
            {context.compactAt
              ? ` Older turns are summarized automatically at ${formatTokens(context.compactAt)}.`
              : ' Automatic compaction is off for this model.'}
          </div>
          <Button
            size="sm"
            className="mt-3 w-full gap-1.5"
            busy={asking}
            disabled={busy || asking}
            title={busy ? 'Wait for the agent to finish' : undefined}
            onClick={compact}
          >
            <CompactIcon className="size-3.5" />
            Compact now
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function CompactionNote({ compaction }: { compaction: Compaction }) {
  const { status, trigger, before, after, error } = compaction
  const label =
    status === 'running'
      ? trigger === 'auto'
        ? 'Context is full, summarizing older turns'
        : 'Summarizing older turns'
      : status === 'error'
        ? `Could not compact the context: ${error ?? 'unknown error'}`
        : 'Context compacted'

  return (
    <div
      className={cn(
        'flex items-center gap-3 text-[12px]',
        status === 'error' ? 'text-danger' : 'text-muted',
      )}
    >
      <div className="bg-line h-px flex-1" />
      <span className="inline-flex items-center gap-1.5">
        <CompactIcon className="size-3.5" />
        {status === 'running' ? <Shimmer>{label}</Shimmer> : label}
        {status === 'done' && before ? (
          <span className="text-faint tabular-nums">
            {formatTokens(before)}
            {after ? ` to ${formatTokens(after)}` : ''} tokens
            {trigger === 'auto' ? ', automatic' : ''}
          </span>
        ) : null}
      </span>
      <div className="bg-line h-px flex-1" />
    </div>
  )
}
