import { type ReactNode, useState } from 'react'
import type { CostRange, CostReport, CostUnit, Provider } from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { Card, Segmented, Skeleton } from '@/components/common/ui'
import { PROVIDER_UI } from '@/components/providers'
import { ProviderSelect } from '@/components/settings/Providers'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatAmount, formatTokens, orderedTokens, tokenLabel } from '@/lib/cost'
import { useLoad } from '@/lib/hooks'
import { modelName, useModels } from '@/lib/models'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'
import { href } from '@/lib/route'
import { useCostUnit, useSettings } from '@/lib/settings'

const RANGES: { id: CostRange; label: string }[] = [
  { id: 'month', label: 'This month' },
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
]

const CHART_HEIGHT_PX = 96
const STAT_TILES = 4
const MIN_BAR_PX = 2
const FULL_PERCENT = 100

const AMOUNT_LABELS: Record<CostUnit, string> = {
  credits: 'Credits',
  usd: 'Estimated value',
  tokens: 'Tokens',
}

function formatDay(day: string, month: 'short' | 'long'): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString([], { month, day: 'numeric' })
}

function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function restOfMonth(days: CostReport['days']): string[] {
  if (!days.length) return []

  const cursor = new Date(`${days[days.length - 1].day}T00:00:00`)
  const month = cursor.getMonth()
  const rest: string[] = []
  cursor.setDate(cursor.getDate() + 1)
  while (cursor.getMonth() === month) {
    rest.push(isoDay(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }

  return rest
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-raised rounded-2xl px-4 py-3">
      <div className="text-muted text-[11.5px]">{label}</div>
      <div className="text-fg mt-0.5 text-[18px] font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function DayChart({
  days,
  upcoming,
  unit,
}: {
  days: CostReport['days']
  upcoming: string[]
  unit: CostUnit
}) {
  const top = Math.max(...days.map((d) => d.amount), 0)
  const [hover, setHover] = useState<number>()
  const shown = hover === undefined ? undefined : days[hover]
  const lastDay = upcoming.length ? upcoming[upcoming.length - 1] : days[days.length - 1]?.day

  return (
    <div>
      <div className="text-muted mb-2 flex h-4 items-center justify-between text-[11.5px]">
        <span>Per day</span>
        {shown ? (
          <span className="text-text tabular-nums">
            {formatDay(shown.day, 'short')}: {formatAmount(shown.amount, unit)}
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
                d.amount ? (hover === i ? 'bg-brand-strong' : 'bg-brand') : 'bg-line',
              )}
              style={{
                height: top ? Math.max(MIN_BAR_PX, (d.amount / top) * CHART_HEIGHT_PX) : MIN_BAR_PX,
              }}
            />
          </div>
        ))}
        {upcoming.map((day) => (
          <div
            key={day}
            className="bg-line/50 min-w-0 flex-1 rounded-t-[3px]"
            style={{ height: MIN_BAR_PX }}
          />
        ))}
      </div>
      <div className="text-faint mt-1.5 flex justify-between text-[11px]">
        <span>{days.length ? formatDay(days[0].day, 'short') : ''}</span>
        <span>{lastDay ? formatDay(lastDay, 'short') : ''}</span>
      </div>
    </div>
  )
}

function Breakdown({
  title,
  rows,
  unit,
}: {
  title: string
  rows: { key: string; label: ReactNode; amount: number }[]
  unit: CostUnit
}) {
  const top = Math.max(...rows.map((r) => r.amount), 0)

  return (
    <div>
      <div className="text-muted mb-2 text-[11.5px]">{title}</div>
      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.key}>
            <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
              <span className="text-text min-w-0 truncate">{row.label}</span>
              <span className="text-fg shrink-0 font-medium tabular-nums">
                {formatAmount(row.amount, unit)}
              </span>
            </div>
            <div className="bg-raised mt-1 h-1.5 overflow-hidden rounded-full">
              <div
                className="bg-brand h-full rounded-full"
                style={{ width: `${top ? (row.amount / top) * FULL_PERCENT : 0}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Usage({ provider }: { provider: Provider }) {
  const [range, setRange] = useState<CostRange>('month')
  const { value: report, loading } = useLoad(() => api.cost(range, provider), [range, provider])
  const skeleton = useSkeleton(loading)
  const models = useModels(provider)
  const unit = useCostUnit(provider)
  const sum = (kinds: string[]) => kinds.reduce((n, kind) => n + (report?.tokens[kind] ?? 0), 0)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-muted max-w-[460px] text-[12px] leading-relaxed">
          {PROVIDER_UI[provider].usageNote}
        </div>
        <Segmented
          label="Range"
          value={range}
          options={RANGES.map((r) => ({ value: r.id, label: r.label }))}
          onChange={setRange}
        />
      </div>

      {skeleton || !report ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Array.from({ length: STAT_TILES }, (_, i) => (
              <Skeleton key={i} className="h-[62px] rounded-2xl" />
            ))}
          </div>
          <Skeleton className="h-24 rounded-xl" />
        </div>
      ) : (
        <div className={cn('space-y-6 transition-opacity', loading && 'opacity-60')}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label={AMOUNT_LABELS[unit]} value={formatAmount(report.amount, unit)} />
            <Stat label="Requests" value={report.requests.toLocaleString()} />
            <Stat
              label="Tokens in"
              value={formatTokens(sum(['input', 'cache_read', 'cache_write']))}
            />
            <Stat label="Tokens out" value={formatTokens(sum(['output']))} />
          </div>

          {report.requests ? (
            <>
              <DayChart
                days={report.days}
                upcoming={range === 'month' ? restOfMonth(report.days) : []}
                unit={unit}
              />
              <div className="grid gap-6 md:grid-cols-2">
                <Breakdown
                  title="By model"
                  unit={unit}
                  rows={report.models.map((m) => ({
                    key: m.model,
                    label: modelName(models, m.model),
                    amount: m.amount,
                  }))}
                />
                <Breakdown
                  title="Most expensive threads"
                  unit={unit}
                  rows={report.threads.map((t) => ({
                    key: t.id,
                    label: (
                      <a
                        href={href({ page: 'thread', id: t.id })}
                        className="hover:text-brand-strong hover:underline"
                      >
                        {t.title}
                      </a>
                    ),
                    amount: t.amount,
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
              No {PROVIDER_BRANDS[provider].name} usage in this range.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function CostSettings() {
  const { settings, providers } = useSettings()
  const [provider, setProvider] = useState<Provider>(settings.provider)
  const { Plan } = PROVIDER_UI[provider]

  return (
    <Card className="divide-line divide-y">
      <div className="flex items-center justify-between gap-3 px-5 py-3.5">
        <div className="text-fg text-[13.5px] font-semibold">Usage</div>
        <div className="shrink-0">
          <ProviderSelect providers={providers} value={provider} onChange={setProvider} />
        </div>
      </div>
      <div className="px-5 py-4">
        <Plan />
      </div>
      <div className="px-5 py-5">
        <Usage provider={provider} />
      </div>
    </Card>
  )
}
