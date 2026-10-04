import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BellRing,
  ExternalLink,
  Gauge,
  HeartPulse,
  RefreshCw,
  ScrollText,
  Sparkles,
  Timer,
} from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import type { DatadogStatus, HealthPoint, InstanceHealth } from '@shared/types.ts'
import {
  DATADOG_PURPLE,
  DatadogBadge,
  DatadogConnectModal,
  DatadogMatches,
  useDatadog,
} from '@/components/datadog/Datadog'
import { useInstances } from '@/components/InstancePicker'
import { Button, Card, Page, Select, Skeleton, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href } from '@/lib/route'

const INSTANCE_KEY = 'ov-agent.health-instance'
const RANGES = ['1h', '24h', '7d'] as const
type Range = (typeof RANGES)[number]
const RANGE_WORDS: Record<Range, string> = { '1h': 'hour', '24h': '24 hours', '7d': '7 days' }

function Sparkline({
  points,
  color,
  height = 40,
}: {
  points: HealthPoint[]
  color: string
  height?: number
}) {
  const width = 240
  if (points.length < 2)
    return <div style={{ height }} className="bg-raised w-full rounded-full opacity-60" />
  const xs = points.map((p) => p.t)
  const ys = points.map((p) => p.v)
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)]
  const [y0, y1] = [Math.min(0, ...ys), Math.max(...ys) || 1]
  const x = (t: number) => ((t - x0) / (x1 - x0 || 1)) * width
  const y = (v: number) => height - 3 - ((v - y0) / (y1 - y0 || 1)) * (height - 6)
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`)
  const area = `${line.join(' ')} L${width},${height} L0,${height} Z`
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height }}
    >
      <path d={area} fill={color} opacity={0.12} />
      <path
        d={line.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.75}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function fmt(value: number, unit: string): string {
  if (unit === '%') return `${value.toFixed(value >= 10 ? 0 : 1)}%`
  if (unit === 'B') {
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let v = value
    let i = 0
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024
      i++
    }
    return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`
  }
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`
  return value.toFixed(value >= 10 ? 0 : 2)
}

const total = (points?: HealthPoint[]) => (points ?? []).reduce((sum, p) => sum + p.v, 0)

function Tile({
  icon: Icon,
  title,
  tone = 'brand',
  children,
  href,
}: {
  icon: typeof Activity
  title: string
  tone?: 'brand' | 'danger' | 'warn' | 'ok' | 'dd'
  children: ReactNode
  href?: string
}) {
  const tones = {
    brand: 'bg-brand-soft text-brand-strong',
    danger: 'bg-danger-soft text-danger',
    warn: 'bg-warn-soft text-warn',
    ok: 'bg-ok-soft text-ok',
    dd: '',
  }
  return (
    <Card className="flex min-w-0 flex-col p-4">
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-full',
            tones[tone],
          )}
          style={tone === 'dd' ? { background: `${DATADOG_PURPLE}14`, color: DATADOG_PURPLE } : {}}
        >
          <Icon className="size-4" />
        </span>
        <span className="text-fg min-w-0 flex-1 truncate text-[13px] font-semibold">{title}</span>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${title} in Datadog`}
            className="text-faint hover:text-brand-strong hover:bg-raised flex size-7 items-center justify-center rounded-full"
          >
            <ExternalLink className="size-3.5" />
          </a>
        ) : null}
      </div>
      <div className="mt-3 flex min-h-0 flex-1 flex-col">{children}</div>
    </Card>
  )
}

function Missing({ text }: { text?: string }) {
  return <div className="text-faint text-[12px] leading-relaxed">{text ?? 'No data.'}</div>
}

const STATE_TONE: Record<string, string> = {
  Alert: 'bg-danger',
  Warn: 'bg-warn',
  'No Data': 'bg-line-strong',
  OK: 'bg-ok',
}

function Report({ report, status }: { report: InstanceHealth; status: DatadogStatus }) {
  const monitors = report.monitors ?? []
  const alerting = monitors.filter((m) => m.state !== 'OK')
  const count = (state: string) => monitors.filter((m) => m.state === state).length
  const errors = total(report.errorSeries)
  const logs = total(report.logSeries)
  const previous = report.previousErrors ?? 0
  const change = previous ? Math.round(((errors - previous) / previous) * 100) : null
  const slowest = report.slowEndpoints?.[0]
  const failures = report.onevizion ?? []

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile
          icon={BellRing}
          title="Monitors"
          tone={count('Alert') ? 'danger' : count('Warn') ? 'warn' : 'ok'}
          href={report.links.monitors}
        >
          {status.permissions.monitors ? (
            <>
              <div className="text-fg text-[24px] leading-none font-semibold">
                {count('Alert') + count('Warn')}
                <span className="text-muted ml-1.5 text-[12.5px] font-normal">alerting</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px]">
                {['Alert', 'Warn', 'No Data', 'OK'].map((s) => (
                  <span key={s} className="text-muted inline-flex items-center gap-1.5">
                    <span className={cn('size-2 rounded-full', STATE_TONE[s])} />
                    {count(s)} {s === 'Warn' ? 'warning' : s.toLowerCase()}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <Missing text="The key cannot read monitors (monitors_read)." />
          )}
        </Tile>
        <Tile
          icon={AlertTriangle}
          title="Error logs"
          tone={change !== null && change > 50 ? 'danger' : 'brand'}
          href={report.links.logs}
        >
          {status.permissions.logs ? (
            <>
              <div className="flex items-end gap-2">
                <span className="text-fg text-[24px] leading-none font-semibold">
                  {fmt(errors, '')}
                </span>
                {change !== null ? (
                  <span
                    className={cn(
                      'inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11px] font-medium',
                      change > 0 ? 'bg-danger-soft text-danger' : 'bg-ok-soft text-ok',
                    )}
                  >
                    {change > 0 ? (
                      <ArrowUpRight className="size-3" />
                    ) : (
                      <ArrowDownRight className="size-3" />
                    )}
                    {Math.abs(change)}%
                  </span>
                ) : null}
              </div>
              <div className="mt-2">
                <Sparkline points={report.errorSeries ?? []} color="#ce2605" />
              </div>
            </>
          ) : (
            <Missing text="The key cannot read logs (logs_read_data)." />
          )}
        </Tile>
        <Tile
          icon={ScrollText}
          title="Log volume"
          href={report.links.logs.replace('status%3Aerror', '')}
        >
          {status.permissions.logs ? (
            <>
              <div className="text-fg text-[24px] leading-none font-semibold">{fmt(logs, '')}</div>
              <div className="mt-2">
                <Sparkline points={report.logSeries ?? []} color="#1e88e5" />
              </div>
            </>
          ) : (
            <Missing />
          )}
        </Tile>
        <Tile icon={Timer} title="Slowest endpoint" tone="dd" href={report.links.apm}>
          {!status.permissions.apm ? (
            <Missing text="The key cannot read APM (apm_read)." />
          ) : slowest ? (
            <>
              <div className="text-fg text-[24px] leading-none font-semibold">
                {slowest.p95Ms >= 1000
                  ? `${(slowest.p95Ms / 1000).toFixed(1)}s`
                  : `${Math.round(slowest.p95Ms)}ms`}
                <span className="text-muted ml-1.5 text-[12.5px] font-normal">p95</span>
              </div>
              <div className="text-muted mt-2 truncate font-mono text-[11.5px]">
                {slowest.resource}
              </div>
            </>
          ) : (
            <Missing text={report.errors.slowEndpoints ?? 'No traces in this window.'} />
          )}
        </Tile>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-4 xl:col-span-2">
          <div className="flex items-center gap-2 pb-2">
            <span className="text-fg flex-1 text-[13px] font-semibold">Top errors</span>
            <a
              href={report.links.logs}
              target="_blank"
              rel="noreferrer"
              className="text-brand-strong inline-flex items-center gap-1 text-[12px] font-medium hover:underline"
            >
              Open in Datadog <ExternalLink className="size-3" />
            </a>
          </div>
          {report.topErrors?.length ? (
            <div className="space-y-1">
              {report.topErrors.map((e) => (
                <div key={e.pattern} className="hover:bg-raised rounded-2xl px-3 py-2">
                  <div className="flex items-start gap-3">
                    <span className="bg-danger-soft text-danger mt-0.5 inline-flex h-6 min-w-10 shrink-0 items-center justify-center rounded-full px-2 text-[11.5px] font-semibold">
                      {e.count}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-fg line-clamp-2 font-mono text-[12px] leading-relaxed break-words">
                        {e.pattern}
                      </div>
                      <div className="text-faint mt-0.5 text-[11px]">
                        {e.service ? `${e.service} - ` : ''}last {e.last} UTC
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Missing
              text={
                report.errors.topErrors ??
                (status.permissions.logs ? 'No error logs in this window.' : undefined)
              }
            />
          )}
        </Card>

        <Card className="p-4">
          <div className="text-fg pb-2 text-[13px] font-semibold">Alerting monitors</div>
          {alerting.length ? (
            <div className="space-y-0.5">
              {alerting.slice(0, 10).map((m) => (
                <a
                  key={m.id}
                  href={`${report.appUrl}/monitors/${m.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:bg-raised flex items-center gap-2.5 rounded-full px-3 py-2"
                >
                  <span className={cn('size-2 shrink-0 rounded-full', STATE_TONE[m.state])} />
                  <span className="text-fg min-w-0 flex-1 truncate text-[12.5px]">{m.name}</span>
                  <span className="text-faint shrink-0 text-[11px]">{m.state}</span>
                </a>
              ))}
            </div>
          ) : (
            <Missing
              text={
                report.errors.monitors ??
                (status.permissions.monitors ? 'Nothing alerting.' : undefined)
              }
            />
          )}
        </Card>
      </div>

      {report.metrics?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {report.metrics.map((m) => {
            const values = m.points.map((p) => p.v)
            const latest = values.at(-1) ?? 0
            return (
              <Card key={m.title} className="p-4">
                <div className="text-muted flex items-center gap-1.5 text-[12px] font-medium">
                  <Gauge className="size-3.5" /> {m.title}
                </div>
                <div className="text-fg mt-1.5 text-[19px] font-semibold">
                  {fmt(latest, m.unit)}
                </div>
                <div className="text-faint text-[11px]">
                  max {fmt(Math.max(...values), m.unit)}
                  {m.hosts > 1 ? ` - ${m.hosts} hosts averaged` : ''}
                </div>
                <div className="mt-2">
                  <Sparkline points={m.points} color={DATADOG_PURPLE} height={34} />
                </div>
              </Card>
            )
          })}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-4">
          <div className="text-fg pb-2 text-[13px] font-semibold">Slow endpoints (p95)</div>
          {report.slowEndpoints?.length ? (
            <div className="space-y-0.5">
              {report.slowEndpoints.map((s) => (
                <div key={s.resource} className="flex items-center gap-2.5 px-1 py-1.5">
                  <span className="text-fg min-w-0 flex-1 truncate font-mono text-[11.5px]">
                    {s.resource}
                  </span>
                  <span className="text-faint shrink-0 text-[11px]">{s.count} calls</span>
                  <span className="text-fg w-16 shrink-0 text-right text-[12px] font-medium">
                    {s.p95Ms >= 1000
                      ? `${(s.p95Ms / 1000).toFixed(1)}s`
                      : `${Math.round(s.p95Ms)}ms`}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Missing
              text={status.permissions.apm ? 'No traces in this window.' : 'APM is not readable.'}
            />
          )}
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 pb-2">
            <span className="text-fg flex-1 text-[13px] font-semibold">Events</span>
            <a
              href={report.links.events}
              target="_blank"
              rel="noreferrer"
              aria-label="Open events in Datadog"
              className="text-faint hover:text-brand-strong"
            >
              <ExternalLink className="size-3.5" />
            </a>
          </div>
          {report.events?.length ? (
            <div className="space-y-2.5">
              {report.events.slice(0, 8).map((e, i) => (
                <div key={i} className="flex gap-2.5">
                  <span className="bg-brand mt-1.5 size-1.5 shrink-0 rounded-full" />
                  <div className="min-w-0">
                    <div className="text-fg truncate text-[12.5px]">{e.title || e.message}</div>
                    <div className="text-faint text-[11px]">
                      {e.time} UTC{e.source ? ` - ${e.source}` : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Missing
              text={
                report.errors.events ??
                (status.permissions.events ? 'No events in this window.' : undefined)
              }
            />
          )}
        </Card>
        <Card className="p-4">
          <div className="text-fg flex items-center gap-2 pb-2 text-[13px] font-semibold">
            <HeartPulse className="text-brand-strong size-3.5" /> OneVizion failures
          </div>
          {failures.length ? (
            <div className="space-y-0.5">
              {failures.map((f) => (
                <div key={f.type} className="flex items-center gap-2.5 px-1 py-1.5">
                  <span className="text-fg min-w-0 flex-1 truncate text-[12.5px]">{f.type}</span>
                  <span className="text-faint shrink-0 text-[11px]">{f.last}</span>
                  <span className="bg-danger-soft text-danger inline-flex h-6 min-w-9 items-center justify-center rounded-full px-2 text-[11.5px] font-semibold">
                    {f.count}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Missing
              text={
                report.errors.onevizion
                  ? `Could not read processes: ${report.errors.onevizion}`
                  : 'No failed processes in this window.'
              }
            />
          )}
        </Card>
      </div>
    </div>
  )
}

export function HealthPage() {
  const { status, setStatus } = useDatadog()
  const { instances } = useInstances()
  const signedIn = useMemo(() => (instances ?? []).filter((i) => i.valid), [instances])
  const [alias, setAlias] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const [range, setRange] = useState<Range>('24h')
  const [report, setReport] = useState<InstanceHealth>()
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [asking, setAsking] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (instances && !signedIn.some((i) => i.alias === alias)) setAlias(signedIn[0]?.alias ?? '')
  }, [instances])
  useEffect(() => {
    if (alias) localStorage.setItem(INSTANCE_KEY, alias)
  }, [alias])

  const current = signedIn.find((i) => i.alias === alias)
  const label = current
    ? current.tenant
      ? `${current.host} / ${current.tenant}`
      : current.host
    : ''

  useEffect(() => {
    if (!status?.connected || !alias) return
    let alive = true
    setLoading(true)
    setError(undefined)
    api
      .instanceHealth(alias, range)
      .then((r) => alive && setReport(r))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [alias, range, status?.connected, status?.matches, tick])

  const ask = async () => {
    setAsking(true)
    try {
      const { id } = await api.startRun({
        prompt: `Check the health of ${label} over the last ${RANGE_WORDS[range]}. Use Datadog: alerting monitors, events such as deploys and restarts, error logs grouped by pattern, and server metrics. Line them up with failed OneVizion processes in the same window. Tell me what changed or is failing, the likely cause, and what to do.`,
        instance: alias,
      })
      go({ page: 'run', id })
    } finally {
      setAsking(false)
    }
  }

  const actions = status?.connected ? (
    <>
      <div className="w-[260px]">
        <Select
          className="w-full"
          value={alias}
          onChange={setAlias}
          placeholder={instances ? 'No signed-in instance' : 'Loading...'}
          options={signedIn.map((i) => ({
            value: i.alias,
            label: i.tenant ? `${i.host} / ${i.tenant}` : i.host,
          }))}
        />
      </div>
      <div className="bg-raised ml-1 flex rounded-full p-1">
        {RANGES.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRange(r)}
            className={cn(
              'h-7 min-w-11 rounded-full px-3 text-[12.5px] font-medium transition-colors',
              r === range ? 'text-fg bg-white shadow-sm' : 'text-muted hover:text-fg',
            )}
          >
            {r}
          </button>
        ))}
      </div>
      <Button
        variant="ghost"
        aria-label="Refresh"
        disabled={loading || !alias}
        onClick={() => setTick((t) => t + 1)}
      >
        {loading ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}
      </Button>
      <Button variant="primary" disabled={!alias || asking} onClick={() => void ask()}>
        {asking ? <Spinner className="size-3.5" /> : <Sparkles className="size-3.5" />} Ask the
        agent
      </Button>
    </>
  ) : null

  const subtitle = (
    <span className="inline-flex items-center gap-1.5">
      {report?.scope && label ? (
        <>
          {label} - <span className="font-mono">{report.scope}</span>
          <a href={href({ page: 'settings' })} className="text-brand-strong hover:underline">
            Change match
          </a>
        </>
      ) : (
        'Errors, latency, alerts and server metrics per instance, from Datadog.'
      )}
    </span>
  )

  let body: ReactNode
  if (!status || (status.connected && !instances)) {
    body = (
      <div className="grid gap-4 p-6 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i} className="space-y-3 p-4">
            <Skeleton className="h-8 w-8 rounded-full" />
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-8 w-full" />
          </Card>
        ))}
      </div>
    )
  } else if (!status.connected) {
    body = (
      <div className="flex h-full items-center justify-center p-6">
        <Card className="w-full max-w-[480px] p-6 text-center">
          <div className="flex justify-center">
            <DatadogBadge size="lg" />
          </div>
          <div className="text-fg mt-4 text-[15px] font-semibold">Connect Datadog</div>
          <div className="text-muted mt-1 text-[13px] leading-relaxed">
            See each instance's alerting monitors, error logs, slow endpoints and server metrics
            next to its failed OneVizion processes. The agent can then read Datadog in runs too.
            Read-only, with your own keys.
          </div>
          <Button className="mt-5" variant="primary" size="lg" onClick={() => setConnecting(true)}>
            Connect Datadog
          </Button>
        </Card>
      </div>
    )
  } else if (!alias) {
    body = (
      <div className="text-muted flex h-full items-center justify-center p-6 text-[13px]">
        Sign in to an instance in Settings first.
      </div>
    )
  } else if (report && !report.scope && report.instance === alias) {
    body = (
      <div className="mx-auto max-w-[860px] p-6">
        <Card className="overflow-hidden">
          <div className="flex items-start gap-3.5 px-5 pt-5">
            <DatadogBadge />
            <div>
              <div className="text-fg text-[14px] font-semibold">Match {label} to Datadog</div>
              <div className="text-muted mt-0.5 text-[12.5px] leading-relaxed">
                Tell Health which servers in Datadog belong to this instance. Suggest matches looks
                at the hosts and services that sent logs in the last day.
              </div>
            </div>
          </div>
          <div className="mt-3">
            <DatadogMatches status={status} onSaved={setStatus} only={alias} />
          </div>
        </Card>
      </div>
    )
  } else if (error) {
    body = <div className="text-danger p-6 text-[13px]">{error}</div>
  } else if (!report || report.instance !== alias || report.range !== range) {
    body = (
      <div className="flex h-full items-center justify-center p-6">
        <Spinner className="text-brand size-6" />
      </div>
    )
  } else {
    body = (
      <div className={cn('p-6 transition-opacity', loading && 'opacity-60')}>
        <Report report={report} status={status} />
      </div>
    )
  }

  return (
    <Page title="Health" subtitle={subtitle} actions={actions}>
      {body}
      <DatadogConnectModal
        open={connecting}
        status={status}
        onClose={() => setConnecting(false)}
        onConnected={(s) => {
          setStatus(s)
          setConnecting(false)
        }}
      />
    </Page>
  )
}
