import { ArrowPathIcon } from '@heroicons/react/24/outline'
import { useEffect, useState } from 'react'
import type { CopilotAccount, CostRange, CostReport } from '@shared/types.ts'
import { AccountRow } from '@/components/datadog/Datadog'
import { useModels } from '@/components/ModelPicker'
import { useSkeleton } from '@/components/skeletons'
import { reportError } from '@/components/Toasts'
import { Card, GithubMark, IconBadge, IconButton, Skeleton } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatCredits, formatTokens, orderedTokens, tokenLabel } from '@/lib/cost'
import { href } from '@/lib/route'

const RANGES: { id: CostRange; label: string }[] = [
  { id: 'month', label: 'This month' },
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
]

const CHART_HEIGHT_PX = 96
const STAT_TILES = 4
const MIN_BAR_PX = 2

function shortDay(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function longDate(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString([], {
    month: 'long',
    day: 'numeric',
  })
}

function planName(plan: string): string {
  return plan ? `${plan[0].toUpperCase()}${plan.slice(1)} plan` : 'Copilot'
}

function AccountCard() {
  const [account, setAccount] = useState<CopilotAccount>()
  const [loading, setLoading] = useState(true)
  const skeleton = useSkeleton(loading)

  const load = () => {
    setLoading(true)
    api
      .copilotAccount()
      .then(setAccount, reportError)
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const detail = !account
    ? 'Usage could not be read from GitHub.'
    : account.tokenBased
      ? `${formatCredits(account.creditsUsed ?? 0)} credits used this cycle across all your Copilot use${
          account.resetDate ? `. Resets ${longDate(account.resetDate)}.` : '.'
        }`
      : account.unlimited
        ? 'Unlimited premium requests.'
        : `${(account.entitlement ?? 0) - (account.remaining ?? 0)} of ${account.entitlement ?? 0} premium requests used this cycle.`

  return (
    <Card>
      <AccountRow
        badge={
          <IconBadge tone="neutral">
            <GithubMark className="size-5" />
          </IconBadge>
        }
        title={account ? `GitHub Copilot, ${planName(account.plan)}` : 'GitHub Copilot'}
        detail={skeleton ? <Skeleton className="mt-1.5 h-2.5 w-72" /> : detail}
        action={
          <IconButton label="Refresh" disabled={loading} onClick={load}>
            <ArrowPathIcon className={cn('size-4', loading && 'animate-spin')} />
          </IconButton>
        }
      />
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-raised rounded-2xl px-4 py-3">
      <div className="text-muted text-[11.5px]">{label}</div>
      <div className="text-fg mt-0.5 text-[18px] font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function DayChart({ days }: { days: CostReport['days'] }) {
  const top = Math.max(...days.map((d) => d.credits), 0)
  const [hover, setHover] = useState<number>()
  const shown = hover === undefined ? undefined : days[hover]

  return (
    <div>
      <div className="text-muted mb-2 flex h-4 items-center justify-between text-[11.5px]">
        <span>Credits per day</span>
        {shown ? (
          <span className="text-text tabular-nums">
            {shortDay(shown.day)}: {formatCredits(shown.credits)}
          </span>
        ) : null}
      </div>
      <div
        className="flex items-end gap-[3px]"
        style={{ height: CHART_HEIGHT_PX }}
        onMouseLeave={() => setHover(undefined)}
      >
        {days.map((d, i) => (
          <div
            key={d.day}
            className="flex h-full min-w-0 flex-1 items-end"
            onMouseEnter={() => setHover(i)}
          >
            <div
              className={cn(
                'w-full rounded-t-[3px] transition-colors',
                d.credits ? (hover === i ? 'bg-brand-strong' : 'bg-brand') : 'bg-line',
              )}
              style={{
                height: top
                  ? Math.max(MIN_BAR_PX, (d.credits / top) * CHART_HEIGHT_PX)
                  : MIN_BAR_PX,
              }}
            />
          </div>
        ))}
      </div>
      <div className="text-faint mt-1.5 flex justify-between text-[11px]">
        <span>{days.length ? shortDay(days[0].day) : ''}</span>
        <span>{days.length ? shortDay(days[days.length - 1].day) : ''}</span>
      </div>
    </div>
  )
}

function Breakdown({
  title,
  rows,
  total,
}: {
  title: string
  rows: { key: string; label: React.ReactNode; credits: number }[]
  total: number
}) {
  return (
    <div>
      <div className="text-muted mb-2 text-[11.5px]">{title}</div>
      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.key}>
            <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
              <span className="text-text min-w-0 truncate">{row.label}</span>
              <span className="text-fg shrink-0 font-medium tabular-nums">
                {formatCredits(row.credits)}
              </span>
            </div>
            <div className="bg-raised mt-1 h-1.5 overflow-hidden rounded-full">
              <div
                className="bg-brand h-full rounded-full"
                style={{ width: `${total ? (row.credits / total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function AgentUsage() {
  const [range, setRange] = useState<CostRange>('month')
  const [report, setReport] = useState<CostReport>()
  const [loading, setLoading] = useState(true)
  const skeleton = useSkeleton(loading)
  const models = useModels()
  const name = (id: string) => models.find((m) => m.id === id)?.name ?? id

  useEffect(() => {
    setLoading(true)
    api
      .cost(range)
      .then(setReport, reportError)
      .finally(() => setLoading(false))
  }, [range])

  const sum = (kinds: string[]) => kinds.reduce((n, kind) => n + (report?.tokens[kind] ?? 0), 0)

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-fg text-[13.5px] font-semibold">OV Agent usage</div>
          <div className="text-muted text-[12px]">
            Credits Copilot charged for this app's requests.
          </div>
        </div>
        <div className="bg-raised flex rounded-full p-1">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setRange(r.id)}
              className={cn(
                'h-7 rounded-full px-3 text-[12.5px] font-medium transition-colors',
                r.id === range ? 'text-fg bg-white shadow-sm' : 'text-muted hover:text-fg',
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {skeleton || !report ? (
        <div className="mt-5 space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Array.from({ length: STAT_TILES }, (_, i) => (
              <Skeleton key={i} className="h-[62px] rounded-2xl" />
            ))}
          </div>
          <Skeleton className="h-24 rounded-xl" />
        </div>
      ) : (
        <div className={cn('mt-5 space-y-6 transition-opacity', loading && 'opacity-60')}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Credits" value={formatCredits(report.credits)} />
            <Stat label="Requests" value={report.requests.toLocaleString()} />
            <Stat
              label="Tokens in"
              value={formatTokens(sum(['input', 'cache_read', 'cache_write']))}
            />
            <Stat label="Tokens out" value={formatTokens(sum(['output']))} />
          </div>

          {report.requests ? (
            <>
              <DayChart days={report.days} />
              <div className="grid gap-6 md:grid-cols-2">
                <Breakdown
                  title="By model"
                  total={report.credits}
                  rows={report.models.map((m) => ({
                    key: m.model,
                    label: name(m.model),
                    credits: m.credits,
                  }))}
                />
                <Breakdown
                  title="Most expensive threads"
                  total={report.threads[0]?.credits ?? 0}
                  rows={report.threads.map((t) => ({
                    key: t.id,
                    label: (
                      <a
                        href={href({ page: 'run', id: t.id })}
                        className="hover:text-brand-strong hover:underline"
                      >
                        {t.title}
                      </a>
                    ),
                    credits: t.credits,
                  }))}
                />
              </div>
              <div className="text-muted flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]">
                {orderedTokens(report.tokens).map(([kind, count]) => (
                  <span key={kind}>
                    {tokenLabel(kind)}{' '}
                    <span className="text-text tabular-nums">{formatTokens(count)}</span>
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div className="text-muted py-4 text-center text-[12.5px]">
              No usage recorded in this range yet.
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

export function CostSettings() {
  return (
    <div className="space-y-4">
      <AccountCard />
      <AgentUsage />
    </div>
  )
}
