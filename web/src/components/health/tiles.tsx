import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  CheckCircle as CheckCircleIcon,
  Lock as LockClosedIcon,
  Sparkle as SparklesIcon,
} from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import type { HealthMeta, HealthSection, HealthSections } from '@shared/types.ts'
import datadogMark from '@/assets/datadog.svg'
import oneteamMark from '@/assets/ov-mark.svg'
import pagerdutyMark from '@/assets/pagerduty.svg'
import { useSkeleton } from '@/components/common/skeletons'
import { Card, Skeleton } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { openDraft } from '@/lib/draft'
import { RANGE_WORDS, type Range, type Slot, type Slots } from './data'
import type { CheckState, Level } from './signals'

const MIN_BAR_PERCENT = 2
const FULL_PERCENT = 100

export type Context = { meta: HealthMeta; label: string; alias: string; range: Range; slots: Slots }

export type Vendor = 'pagerduty' | 'datadog' | 'oneteam'

const VENDORS: Record<Vendor, { name: string; mark: string }> = {
  pagerduty: { name: 'PagerDuty', mark: pagerdutyMark },
  datadog: { name: 'Datadog', mark: datadogMark },
  oneteam: { name: 'OneTeam', mark: oneteamMark },
}

export const LEVEL_TEXT: Record<Level, string> = {
  danger: 'text-danger',
  warn: 'text-warn',
  ok: 'text-fg',
}

export const LEVEL_FILL: Record<Level, string> = {
  danger: 'bg-danger',
  warn: 'bg-warn',
  ok: 'bg-brand',
}

export const STATE_DOT: Record<CheckState, string> = {
  danger: 'bg-danger',
  warn: 'bg-warn',
  ok: 'bg-ok',
  off: 'bg-line-strong',
  loading: 'bg-line-strong',
}

export function ask(ctx: Context, prompt: string) {
  openDraft({
    instance: ctx.alias,
    prompt: `${prompt} Instance ${ctx.label}, last ${RANGE_WORDS[ctx.range]}.`,
  })
}

export function Separator() {
  return <span aria-hidden className="bg-line-strong size-[3px] shrink-0 rounded-full" />
}

export function SourceTag({ vendor, area }: { vendor: Vendor; area?: string }) {
  const { name, mark } = VENDORS[vendor]

  return (
    <span className="text-muted inline-flex items-center gap-1.5 text-[11px] font-medium">
      <img src={mark} alt="" className="size-3.5" />
      {name}
      {area ? (
        <>
          <Separator />
          {area}
        </>
      ) : null}
    </span>
  )
}

export function Tile({
  vendor,
  area,
  title,
  aside,
  link,
  onAsk,
  className,
  children,
}: {
  vendor: Vendor
  area?: string
  title: ReactNode
  aside?: ReactNode
  link?: string
  onAsk?: () => void
  className?: string
  children: ReactNode
}) {
  return (
    <Card className={cn('flex min-w-0 flex-col p-5', className)}>
      <div className="flex items-start gap-2 pb-3.5">
        <div className="min-w-0 flex-1">
          <SourceTag vendor={vendor} area={area} />
          <div className="text-fg mt-1 flex flex-wrap items-baseline gap-x-2 text-[14px] font-semibold">
            {title}
            {aside ? <span className="text-muted text-[12px] font-normal">{aside}</span> : null}
          </div>
        </div>
        {onAsk ? (
          <button
            type="button"
            onClick={onAsk}
            title="Ask the agent about this"
            className="text-muted hover:text-brand-strong hover:bg-brand-soft inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium"
          >
            <SparklesIcon className="size-3.5" /> Ask
          </button>
        ) : null}
        {link ? (
          <a
            href={link}
            target="_blank"
            rel="noreferrer"
            title={`Open in ${VENDORS[vendor].name}`}
            className="text-brand-strong hover:bg-brand-soft inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium"
          >
            Open <ArrowTopRightOnSquareIcon className="size-3" />
          </a>
        ) : null}
      </div>
      <div className="-mr-2 min-h-0 flex-1 scrollbar-thin overflow-y-auto pr-2">{children}</div>
    </Card>
  )
}

export function Quiet({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return (
    <div className="text-muted flex items-start gap-2 text-[12.5px]">
      {muted ? (
        <LockClosedIcon className="text-faint mt-0.5 size-3.5 shrink-0" />
      ) : (
        <CheckCircleIcon className="text-ok mt-px size-4 shrink-0" />
      )}
      <span>{children}</span>
    </div>
  )
}

export function RowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-3.5', i % 2 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}

export function Body<K extends HealthSection>({
  slot,
  skeleton,
  children,
}: {
  slot: Slot<K>
  skeleton?: ReactNode
  children: (value: HealthSections[K]) => ReactNode
}) {
  const showSkeleton = useSkeleton(slot.state === 'loading')
  if (showSkeleton) return <>{skeleton ?? <RowsSkeleton />}</>
  if (slot.state === 'loading') return null
  if (slot.state === 'error')
    return <div className="text-danger text-[12.5px] break-words">{slot.error}</div>
  if (slot.state === 'unavailable') return <Quiet muted>{slot.reason}</Quiet>
  return <>{children(slot.value)}</>
}

export function Stat({
  label,
  value,
  level = 'ok',
  hint,
}: {
  label: string
  value: ReactNode
  level?: Level
  hint?: string
}) {
  return (
    <div className="bg-raised min-w-0 rounded-2xl px-3.5 py-2.5" title={hint}>
      <div className="text-muted truncate text-[11.5px]">{label}</div>
      <div
        className={cn(
          'mt-0.5 truncate text-[18px] leading-tight font-semibold tabular-nums',
          LEVEL_TEXT[level],
        )}
      >
        {value}
      </div>
    </div>
  )
}

export function Meter({
  label,
  now,
  worst,
  level,
  worstLevel,
  format,
}: {
  label: string
  now: number
  worst: number
  level: Level
  worstLevel: Level
  format: (v: number) => string
}) {
  const clamp = (v: number) => Math.min(FULL_PERCENT, Math.max(MIN_BAR_PERCENT, v))

  return (
    <div title={`Now ${format(now)}, worst in this window ${format(worst)}`}>
      <div className="flex items-baseline gap-2 text-[11.5px]">
        <span className="text-muted flex-1 truncate">{label}</span>
        {worstLevel !== 'ok' && level === 'ok' ? (
          <span className={cn('text-[10.5px]', LEVEL_TEXT[worstLevel])}>peak {format(worst)}</span>
        ) : null}
        <span className={cn('font-semibold tabular-nums', LEVEL_TEXT[level])}>{format(now)}</span>
      </div>
      <div className="bg-line relative mt-1 h-1.5 rounded-full">
        <div
          className={cn('h-full rounded-full', LEVEL_FILL[level])}
          style={{ width: `${clamp(now)}%` }}
        />
        <span
          aria-hidden
          className="bg-fg/50 absolute -top-0.5 h-2.5 w-0.5 rounded-full"
          style={{ left: `calc(${clamp(worst)}% - 1px)` }}
        />
      </div>
    </div>
  )
}

export function Bar({ value, max, fill }: { value: number; max: number; fill: string }) {
  return (
    <div className="bg-line mt-1.5 h-1 overflow-hidden rounded-full">
      <div
        className={cn('h-full rounded-full', fill)}
        style={{ width: `${Math.max(MIN_BAR_PERCENT, (value / max) * FULL_PERCENT)}%` }}
      />
    </div>
  )
}

export function Reading({
  label,
  value,
  level = 'ok',
  hint,
}: {
  label: string
  value: string
  level?: Level
  hint?: string
}) {
  return (
    <div className="flex items-baseline gap-2 text-[11.5px]" title={hint}>
      <span className="text-muted flex-1 truncate">{label}</span>
      <span className={cn('font-semibold tabular-nums', LEVEL_TEXT[level])}>{value}</span>
    </div>
  )
}
