import {
  ArrowPathIcon,
  ArrowTopRightOnSquareIcon,
  ChartBarIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  ServerIcon,
  ShieldCheckIcon,
  ShieldExclamationIcon,
  SparklesIcon,
} from '@heroicons/react/24/outline'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import type {
  DatadogDiscovery,
  DatadogStatus,
  HealthPoint,
  Instance,
  InstanceHealth,
  PagerDutyHealth,
} from '@shared/types.ts'
import {
  DATADOG_PURPLE,
  DatadogBadge,
  DatadogConnectModal,
  useDatadog,
} from '@/components/datadog/Datadog'
import { useInstances } from '@/components/InstancePicker'
import { PagerDutyBadge } from '@/components/pagerduty/PagerDuty'
import {
  type BadgeTone,
  Button,
  Card,
  EmptyState,
  IconBadge,
  Page,
  Select,
  Skeleton,
  Spinner,
} from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { openDraft } from '@/lib/draft'
import { href } from '@/lib/route'

const INSTANCE_KEY = 'ov-agent.health-instance'
const RANGES = ['1h', '24h', '7d'] as const
type Range = (typeof RANGES)[number]
const RANGE_WORDS: Record<Range, string> = { '1h': 'hour', '24h': '24 hours', '7d': '7 days' }

const BLUE = '#42a5f5'
const RED = '#e53935'

function count(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(Math.round(n))
}

function duration(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)}s`
  return `${Math.round(ms)}ms`
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
  return value >= 100 ? count(value) : value.toFixed(2)
}

const total = (points?: HealthPoint[]) => (points ?? []).reduce((sum, p) => sum + p.v, 0)

function clock(ms: number, range: Range): string {
  const d = new Date(ms)
  return range === '7d'
    ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

/** Bars with an optional line on its own scale, time labels and a hover readout. */
function TimeChart({
  bars,
  line,
  barColor,
  lineColor,
  barLabel,
  lineLabel,
  formatBar,
  formatLine,
  range,
  height = 190,
}: {
  bars: HealthPoint[]
  line?: HealthPoint[]
  barColor: string
  lineColor: string
  barLabel: string
  lineLabel?: string
  formatBar: (v: number) => string
  formatLine?: (v: number) => string
  range: Range
  height?: number
}) {
  const [hover, setHover] = useState<number>()
  const width = 600
  const n = bars.length
  if (!n)
    return <div className="text-faint py-12 text-center text-[12.5px]">No data in this window.</div>
  const barMax = Math.max(...bars.map((p) => p.v), 1)
  const lineMax = Math.max(...(line ?? []).map((p) => p.v), 1)
  const slot = width / n
  const y = (v: number, max: number) => height - 4 - (v / max) * (height - 16)
  const path = (line ?? [])
    .slice(0, n)
    .map(
      (p, i) => `${i ? 'L' : 'M'}${(i * slot + slot / 2).toFixed(1)},${y(p.v, lineMax).toFixed(1)}`,
    )
    .join(' ')
  const at = hover ?? -1
  const point = bars[at]
  return (
    <div>
      <div className="text-faint flex justify-between pb-1 text-[11px]">
        <span>
          {barLabel} - max {formatBar(barMax)}
        </span>
        {line?.length && lineLabel && formatLine ? (
          <span>
            {lineLabel} - max {formatLine(lineMax)}
          </span>
        ) : null}
      </div>
      <div
        className="relative"
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          setHover(Math.min(n - 1, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * n))))
        }}
        onMouseLeave={() => setHover(undefined)}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="block w-full"
          style={{ height }}
        >
          {[0.25, 0.5, 0.75].map((f) => (
            <line
              key={f}
              x1={0}
              x2={width}
              y1={height * f}
              y2={height * f}
              stroke="#eceff1"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {bars.map((p, i) => {
            const top = y(p.v, barMax)
            return (
              <rect
                key={p.t}
                x={i * slot + Math.min(1.5, slot * 0.15)}
                y={top}
                width={Math.max(1, slot - Math.min(3, slot * 0.3))}
                height={Math.max(0, height - 4 - top)}
                rx={Math.min(3, slot / 4)}
                fill={barColor}
                opacity={at === -1 || at === i ? 0.75 : 0.35}
              />
            )
          })}
          {path ? (
            <path
              d={path}
              fill="none"
              stroke={lineColor}
              strokeWidth={2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
          {at >= 0 ? (
            <line
              x1={at * slot + slot / 2}
              x2={at * slot + slot / 2}
              y1={0}
              y2={height}
              stroke="#90a4ae"
              strokeDasharray="3 3"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
        </svg>
        {point ? (
          <div
            className="border-line pointer-events-none absolute top-1 z-10 rounded-2xl border bg-white px-3 py-2 text-[11.5px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
            style={{
              left: `${((at + 0.5) / n) * 100}%`,
              transform: `translateX(${at > n * 0.7 ? '-105%' : '5%'})`,
            }}
          >
            <div className="text-fg font-medium">
              {clock(point.t, range === '7d' ? '24h' : range)}
            </div>
            <div className="text-muted mt-0.5 flex items-center gap-1.5 whitespace-nowrap">
              <span className="size-2 rounded-full" style={{ background: barColor }} />
              {barLabel} {formatBar(point.v)}
            </div>
            {line?.[at] && lineLabel && formatLine ? (
              <div className="text-muted flex items-center gap-1.5 whitespace-nowrap">
                <span className="size-2 rounded-full" style={{ background: lineColor }} />
                {lineLabel} {formatLine(line[at].v)}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="text-faint flex justify-between pt-1.5 text-[11px]">
        <span>{clock(bars[0].t, range)}</span>
        <span>{clock(bars[Math.floor(n / 2)].t, range)}</span>
        <span>{clock(bars[n - 1].t, range)}</span>
      </div>
    </div>
  )
}

function Sparkline({
  points,
  color,
  height = 44,
}: {
  points: HealthPoint[]
  color: string
  height?: number
}) {
  const width = 240
  if (points.length < 2) return <div style={{ height }} />
  const ys = points.map((p) => p.v)
  const [lo, hi] = [Math.min(...ys), Math.max(...ys)]
  const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1
  const [y0, y1] = [lo - pad, hi + pad]
  const x = (i: number) => (i / (points.length - 1)) * width
  const y = (v: number) => height - ((v - y0) / (y1 - y0)) * height
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`)
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="block w-full"
      style={{ height }}
    >
      <path d={`${line.join(' ')} L${width},${height} L0,${height} Z`} fill={color} opacity={0.1} />
      <path
        d={line.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.75}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function CardHeader({
  title,
  hint,
  href: link,
}: {
  title: string
  hint?: ReactNode
  href?: string
}) {
  return (
    <div className="flex items-start gap-2 pb-3">
      <div className="min-w-0 flex-1">
        <div className="text-fg text-[13.5px] font-semibold">{title}</div>
        {hint ? <div className="text-muted mt-0.5 text-[12px]">{hint}</div> : null}
      </div>
      {link ? (
        <a
          href={link}
          target="_blank"
          rel="noreferrer"
          className="text-brand-strong hover:bg-brand-soft inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium"
        >
          Datadog <ArrowTopRightOnSquareIcon className="size-3" />
        </a>
      ) : null}
    </div>
  )
}

type Signal = { tone: 'danger' | 'warn' | 'ok'; text: string }

const SIGNAL_DOT: Record<Signal['tone'], string> = {
  danger: 'bg-danger',
  warn: 'bg-warn',
  ok: 'bg-ok',
}

const STATE_DOT: Record<string, string> = {
  Alert: 'bg-danger',
  Warn: 'bg-warn',
  'No Data': 'bg-line-strong',
  OK: 'bg-ok',
}

function signalsOf(report: InstanceHealth, errorChange: number | null): Signal[] {
  const monitors = report.monitors ?? []
  const alerts = monitors.filter((m) => m.state === 'Alert').length
  const warns = monitors.filter((m) => m.state === 'Warn').length
  const errors = total(report.errorSeries)
  const slowest = report.slowEndpoints?.[0]
  const failures = report.onevizion ?? []
  const metric = (title: string) => report.metrics?.find((m) => m.title === title)
  const latest = (title: string) => metric(title)?.points.at(-1)?.v
  const out: Signal[] = []
  const open = report.pagerduty?.open ?? []
  const triggered = open.filter((i) => i.status === 'triggered').length
  if (triggered)
    out.push({
      tone: 'danger',
      text: `${triggered} PagerDuty incident${triggered > 1 ? 's' : ''} triggered`,
    })
  if (open.length - triggered)
    out.push({ tone: 'warn', text: `${open.length - triggered} PagerDuty acknowledged` })
  if (alerts)
    out.push({ tone: 'danger', text: `${alerts} monitor${alerts > 1 ? 's' : ''} alerting` })
  if (warns) out.push({ tone: 'warn', text: `${warns} monitor${warns > 1 ? 's' : ''} warning` })
  if (errorChange !== null && errorChange > 50 && errors >= 10)
    out.push({ tone: 'warn', text: `Error logs up ${errorChange}%` })
  if (slowest && slowest.p95Ms >= 10_000)
    out.push({ tone: 'warn', text: `Slowest endpoint ${duration(slowest.p95Ms)} p95` })
  for (const f of failures.slice(0, 2))
    out.push({
      tone: f.count >= 50 ? 'danger' : 'warn',
      text: `${count(f.count)} failed ${f.type.toLowerCase()} runs`,
    })
  const cpu = latest('CPU')
  if (cpu !== undefined && cpu >= 85) out.push({ tone: 'warn', text: `CPU at ${fmt(cpu, '%')}` })
  const disk = latest('Disk in use')
  if (disk !== undefined && disk >= 90)
    out.push({ tone: 'danger', text: `Disk ${fmt(disk, '%')} full` })
  const memory = latest('Memory usable')
  if (memory !== undefined && memory <= 10)
    out.push({ tone: 'warn', text: `Only ${fmt(memory, '%')} memory free` })
  return out
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'danger' | 'warn' | 'ok'
}) {
  return (
    <div className="sm:border-line min-w-0 px-4 first:pl-0 sm:border-l sm:first:border-l-0">
      <div className="text-muted truncate text-[12px]">{label}</div>
      <div
        className={cn(
          'mt-1 text-[22px] leading-none font-semibold tabular-nums',
          tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : 'text-fg',
        )}
      >
        {value}
      </div>
      {sub ? <div className="text-faint mt-1.5 truncate text-[11.5px]">{sub}</div> : null}
    </div>
  )
}

function Quiet({ children }: { children: ReactNode }) {
  return (
    <div className="text-muted flex items-center gap-2 text-[12.5px]">
      <CheckCircleIcon className="text-ok size-4" />
      {children}
    </div>
  )
}

function SubHead({ children }: { children: ReactNode }) {
  return <div className="text-faint pb-1.5 text-[11.5px] font-medium">{children}</div>
}

const INCIDENT_DOT: Record<string, string> = {
  triggered: 'bg-danger',
  acknowledged: 'bg-warn',
  resolved: 'bg-ok',
}

function when(value: string): string {
  const d = new Date(value)
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
}

function Incidents({ data, range }: { data: PagerDutyHealth; range: Range }) {
  const open = data.open ?? []
  const openIds = new Set(open.map((i) => i.id))
  const recent = (data.incidents ?? []).filter((i) => !openIds.has(i.id))
  const rows = [...open, ...recent].slice(0, 8)
  const primary = data.oncall ?? []
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3 pb-3">
        <PagerDutyBadge />
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13.5px] font-semibold">Incidents</div>
          <div className="text-muted mt-0.5 text-[12px]">
            {`${open.length} open - ${recent.length} more in the last ${RANGE_WORDS[range]}`}
          </div>
        </div>
        {primary.length ? (
          <div className="text-right">
            <div className="text-faint text-[11px] font-medium">On call now</div>
            <div className="text-fg text-[12.5px] font-medium">
              {primary.map((o) => o.user).join(', ')}
            </div>
          </div>
        ) : null}
        <a
          href={data.webUrl ? `${data.webUrl}/incidents` : '#'}
          target="_blank"
          rel="noreferrer"
          className="text-brand-strong hover:bg-brand-soft inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium"
        >
          PagerDuty <ArrowTopRightOnSquareIcon className="size-3" />
        </a>
      </div>
      {rows.length ? (
        <div className="-mx-2 space-y-0.5">
          {rows.map((i) => (
            <a
              key={i.id}
              href={i.url}
              target="_blank"
              rel="noreferrer"
              className="hover:bg-raised flex items-center gap-3 rounded-full px-3 py-2"
            >
              <span className={cn('size-2 shrink-0 rounded-full', INCIDENT_DOT[i.status])} />
              <span className="text-faint w-14 shrink-0 text-[12px] tabular-nums">#{i.number}</span>
              <span className="text-fg min-w-0 flex-1 truncate text-[12.5px]">{i.title}</span>
              {i.urgency === 'high' ? (
                <span className="bg-danger-soft text-danger shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium">
                  high
                </span>
              ) : null}
              <span className="text-faint w-28 shrink-0 text-right text-[11.5px]">
                {when(i.created)}
              </span>
            </a>
          ))}
        </div>
      ) : (
        <Quiet>
          {Object.values(data.errors)[0] ?? `No incidents in the last ${RANGE_WORDS[range]}.`}
        </Quiet>
      )}
    </Card>
  )
}

function Report({
  report,
  status,
  label,
  range,
}: {
  report: InstanceHealth
  status: DatadogStatus
  label: string
  range: Range
}) {
  const monitors = report.monitors ?? []
  const alerting = monitors.filter((m) => m.state !== 'OK')
  const alerts = monitors.filter((m) => m.state === 'Alert').length
  const errors = total(report.errorSeries)
  const previous = report.previousErrors ?? 0
  const errorChange = previous ? Math.round(((errors - previous) / previous) * 100) : null
  const slowest = report.slowEndpoints?.[0]
  const failures = report.onevizion ?? []
  const failed = failures.reduce((sum, f) => sum + f.count, 0)
  const signals = signalsOf(report, errorChange)
  const verdict: { tone: BadgeTone; title: string; icon: typeof CheckCircleIcon } = signals.some(
    (s) => s.tone === 'danger',
  )
    ? { tone: 'danger', title: 'Needs attention', icon: ShieldExclamationIcon }
    : signals.length
      ? { tone: 'warn', title: 'Worth a look', icon: ExclamationTriangleIcon }
      : { tone: 'ok', title: 'Healthy', icon: CheckCircleIcon }
  const requests = report.traffic?.requests ?? []
  const hasTraffic = requests.some((p) => p.v > 0)
  const slowMax = Math.max(...(report.slowEndpoints ?? []).map((s) => s.p95Ms), 1)
  const failMax = Math.max(...failures.map((f) => f.count), 1)

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-5">
          <div className="flex min-w-[280px] flex-1 items-start gap-4">
            <IconBadge icon={verdict.icon} tone={verdict.tone} size="lg" />
            <div className="min-w-0">
              <div className="text-fg text-[17px] font-semibold">{verdict.title}</div>
              <div className="text-muted mt-0.5 text-[12.5px]">
                {label} over the last {RANGE_WORDS[range]}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(signals.length
                  ? signals
                  : [{ tone: 'ok', text: 'No alerts, error spikes or failed runs' } as Signal]
                ).map((s) => (
                  <span
                    key={s.text}
                    className="bg-raised text-text inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[12px]"
                  >
                    <span className={cn('size-1.5 rounded-full', SIGNAL_DOT[s.tone])} />
                    {s.text}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-y-4 sm:grid-cols-4">
            <Stat
              label="Alerting monitors"
              value={status.permissions.monitors ? alerting.length : '-'}
              sub={
                !status.permissions.monitors
                  ? 'No access'
                  : monitors.length
                    ? `${monitors.length} watching this instance`
                    : 'None set up'
              }
              tone={alerts ? 'danger' : alerting.length ? 'warn' : undefined}
            />
            <Stat
              label="Error logs"
              value={status.permissions.logs ? count(errors) : '-'}
              sub={
                errorChange === null
                  ? 'No earlier data'
                  : `${errorChange > 0 ? '+' : ''}${errorChange}% vs previous`
              }
              tone={errorChange !== null && errorChange > 50 && errors >= 10 ? 'warn' : undefined}
            />
            <Stat
              label="Slowest p95"
              value={slowest ? duration(slowest.p95Ms) : '-'}
              sub={
                slowest ? slowest.resource : status.permissions.apm ? 'No traces' : 'No APM access'
              }
              tone={slowest && slowest.p95Ms >= 10_000 ? 'warn' : undefined}
            />
            <Stat
              label="Failed runs"
              value={report.errors.onevizion ? '-' : count(failed)}
              sub={failures[0] ? `Most: ${failures[0].type}` : 'OneVizion processes'}
              tone={failed >= 50 ? 'danger' : failed ? 'warn' : undefined}
            />
          </div>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          {hasTraffic ? (
            <>
              <CardHeader
                title="Requests and latency"
                hint="Requests per interval, with p95 response time"
                href={report.links.apm}
              />
              <TimeChart
                bars={requests}
                line={report.traffic?.p95Ms}
                barColor={BLUE}
                lineColor={DATADOG_PURPLE}
                barLabel="Requests"
                lineLabel="p95"
                formatBar={count}
                formatLine={duration}
                range={range}
              />
            </>
          ) : (
            <>
              <CardHeader
                title="Logs and errors"
                hint="Log lines per interval, with error logs"
                href={report.links.logs}
              />
              <TimeChart
                bars={report.logSeries ?? []}
                line={report.errorSeries}
                barColor={BLUE}
                lineColor={RED}
                barLabel="Logs"
                lineLabel="Errors"
                formatBar={count}
                formatLine={count}
                range={range}
              />
            </>
          )}
        </Card>

        <Card className="p-5">
          <CardHeader title="Failed OneVizion runs" hint="Processes that ended with errors" />
          {report.errors.onevizion ? (
            <div className="text-faint text-[12.5px]">
              Could not read processes: {report.errors.onevizion}
            </div>
          ) : failures.length ? (
            <div className="space-y-3">
              {failures.map((f) => (
                <div key={f.type}>
                  <div className="flex items-baseline gap-2 text-[12.5px]">
                    <span className="text-fg min-w-0 flex-1 truncate font-medium">{f.type}</span>
                    <span className="text-fg font-semibold tabular-nums">{count(f.count)}</span>
                  </div>
                  <div className="bg-raised mt-1.5 h-1.5 overflow-hidden rounded-full">
                    <div
                      className="bg-danger h-full rounded-full"
                      style={{ width: `${Math.max(4, (f.count / failMax) * 100)}%` }}
                    />
                  </div>
                  {f.last ? <div className="text-faint mt-1 text-[11px]">Last {f.last}</div> : null}
                </div>
              ))}
            </div>
          ) : (
            <Quiet>No failed processes in this window.</Quiet>
          )}
        </Card>
      </div>

      {report.pagerduty ? <Incidents data={report.pagerduty} range={range} /> : null}

      {report.metrics?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {report.metrics.map((m) => {
            const latest = m.points.at(-1)?.v ?? 0
            return (
              <Card key={m.title} className="p-4">
                <div className="text-muted text-[12px] font-medium">{m.title}</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-fg text-[20px] font-semibold tabular-nums">
                    {fmt(latest, m.unit)}
                  </span>
                  <span className="text-faint text-[11.5px]">
                    max {fmt(m.max ?? latest, m.unit)}
                  </span>
                </div>
                <div className="mt-2">
                  <Sparkline points={m.points} color={DATADOG_PURPLE} />
                </div>
                {m.hosts > 1 ? (
                  <div className="text-faint mt-1 text-[11px]">{m.hosts} hosts averaged</div>
                ) : null}
              </Card>
            )
          })}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader title="Slowest endpoints" hint="p95 response time" href={report.links.apm} />
          {report.slowEndpoints?.length ? (
            <div className="space-y-2.5">
              {report.slowEndpoints.map((s) => (
                <div key={s.resource}>
                  <div className="flex items-baseline gap-3 text-[12.5px]">
                    <span className="text-fg min-w-0 flex-1 truncate font-mono text-[12px]">
                      {s.resource}
                    </span>
                    <span className="text-faint shrink-0 text-[11.5px]">
                      {count(s.count)} calls
                    </span>
                    <span className="text-fg w-14 shrink-0 text-right font-semibold tabular-nums">
                      {duration(s.p95Ms)}
                    </span>
                  </div>
                  <div className="bg-raised mt-1.5 h-1.5 overflow-hidden rounded-full">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        s.p95Ms >= 10_000 ? 'bg-danger' : s.p95Ms >= 3000 ? 'bg-warn' : 'bg-brand',
                      )}
                      style={{ width: `${Math.max(3, (s.p95Ms / slowMax) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Quiet>
              {status.permissions.apm ? 'No traces in this window.' : 'The key cannot read APM.'}
            </Quiet>
          )}
        </Card>

        <Card className="space-y-5 p-5">
          <div>
            <SubHead>Monitors</SubHead>
            {!status.permissions.monitors ? (
              <div className="text-faint text-[12.5px]">The key cannot read monitors.</div>
            ) : alerting.length ? (
              <div className="-mx-2 space-y-0.5">
                {alerting.slice(0, 6).map((m) => (
                  <a
                    key={m.id}
                    href={`${report.appUrl}/monitors/${m.id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:bg-raised flex h-8 items-center gap-2.5 rounded-full px-2.5"
                  >
                    <span className={cn('size-2 shrink-0 rounded-full', STATE_DOT[m.state])} />
                    <span className="text-fg min-w-0 flex-1 truncate text-[12.5px]">{m.name}</span>
                  </a>
                ))}
              </div>
            ) : (
              <Quiet>
                {monitors.length
                  ? `All ${monitors.length} monitors OK.`
                  : 'No monitors watch this instance.'}
              </Quiet>
            )}
          </div>
          <div>
            <SubHead>Top errors</SubHead>
            {report.topErrors?.length ? (
              <div className="space-y-2">
                {report.topErrors.slice(0, 3).map((e) => (
                  <div key={e.pattern} className="flex items-start gap-2.5">
                    <span className="bg-danger-soft text-danger inline-flex h-5 min-w-8 shrink-0 items-center justify-center rounded-full px-1.5 text-[11px] font-semibold">
                      {count(e.count)}
                    </span>
                    <span className="text-text line-clamp-2 font-mono text-[11.5px] leading-relaxed break-words">
                      {e.pattern}
                    </span>
                  </div>
                ))}
                <a
                  href={report.links.logs}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-strong inline-flex items-center gap-1 text-[12px] font-medium hover:underline"
                >
                  All error logs <ArrowTopRightOnSquareIcon className="size-3" />
                </a>
              </div>
            ) : (
              <Quiet>
                {status.permissions.logs ? 'No error logs.' : 'The key cannot read logs.'}
              </Quiet>
            )}
          </div>
          <div>
            <SubHead>Events</SubHead>
            {report.events?.length ? (
              <div className="space-y-2">
                {report.events.slice(0, 4).map((e, i) => (
                  <div key={i} className="min-w-0">
                    <div className="text-fg truncate text-[12.5px]">{e.title || e.message}</div>
                    <div className="text-faint text-[11px]">{e.time} UTC</div>
                  </div>
                ))}
              </div>
            ) : (
              <Quiet>No deploys, restarts or other events.</Quiet>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}

const PREVIEW = [
  {
    icon: ShieldCheckIcon,
    title: 'A verdict at a glance',
    text: 'Healthy, worth a look or needs attention, with the reasons behind it.',
  },
  {
    icon: ChartBarIcon,
    title: 'Requests and latency',
    text: 'Traffic and p95 response time from APM, hour by hour.',
  },
  {
    icon: ServerIcon,
    title: 'Server metrics',
    text: 'CPU, load, memory, disk and JVM heap of its hosts.',
  },
  {
    icon: ExclamationTriangleIcon,
    title: 'Errors and failed runs',
    text: 'Top error groups next to failed OneVizion processes.',
  },
]

function MatchInstance({
  host,
  alias,
  status,
  onSaved,
}: {
  host: string
  alias: string
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
}) {
  const [found, setFound] = useState<DatadogDiscovery>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [filter, setFilter] = useState('')
  const [logs, setLogs] = useState<number | 'busy'>()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(undefined)
    api
      .datadogDiscover()
      .then((r) => {
        if (!alive) return
        setFound(r)
        const mine = r.suggestions.find((s) => s.alias === alias)
        if (mine?.filter) {
          setFilter(mine.filter)
          setLogs(mine.count)
        }
      })
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [alias])

  useEffect(() => {
    if (!filter.trim()) return setLogs(undefined)
    setLogs('busy')
    const timer = setTimeout(() => {
      api
        .datadogCount(filter)
        .then((r) => setLogs(r.count))
        .catch(() => setLogs(undefined))
    }, 600)
    return () => clearTimeout(timer)
  }, [filter])

  const suggestion = found?.suggestions.find((s) => s.alias === alias && s.filter)
  const label = host.split('.')[0].toLowerCase()
  const values = found?.values ?? []
  const related = values.filter((v) => v.value.toLowerCase().includes(label))
  const others = (related.length ? related : values).slice(0, 8)

  const save = async () => {
    setSaving(true)
    setError(undefined)
    try {
      onSaved(await api.datadogMatches({ ...status.matches, [alias]: filter.trim() }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-[920px] space-y-6 p-6">
      <Card className="p-6">
        <div className="flex items-start gap-4">
          <DatadogBadge size="lg" />
          <div className="min-w-0">
            <div className="text-fg text-[17px] font-semibold">Find {host} in Datadog</div>
            <div className="text-muted mt-1 text-[13px] leading-relaxed">
              Health needs to know which servers in Datadog run this instance. Pick a suggestion or
              write a filter; it applies to every tenant on this host.
            </div>
          </div>
        </div>

        <div className="mt-6 space-y-5">
          {loading ? (
            <div className="bg-raised text-muted flex items-center gap-3 rounded-2xl px-4 py-4 text-[13px]">
              <Spinner className="text-brand size-4" />
              Looking at the hosts and services that sent logs in the last day...
            </div>
          ) : suggestion ? (
            <div className="border-brand/40 bg-brand-soft/40 flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-3.5">
              <SparklesIcon className="text-brand-strong size-5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-fg font-mono text-[13px] font-medium">{suggestion.filter}</div>
                <div className="text-muted mt-0.5 text-[12px]">
                  Suggested - {suggestion.why} - {count(suggestion.count)} logs in the last day
                </div>
              </div>
              <Button
                size="sm"
                variant={filter === suggestion.filter ? 'secondary' : 'primary'}
                onClick={() => setFilter(suggestion.filter)}
              >
                {filter === suggestion.filter ? 'Selected' : 'Use this'}
              </Button>
            </div>
          ) : (
            <div className="bg-raised text-muted rounded-2xl px-4 py-3.5 text-[13px]">
              No host or service name looks like {host}. Pick one below or write a filter.
            </div>
          )}

          {others.length ? (
            <div>
              <div className="text-faint pb-2 text-[12px] font-medium">
                {related.length ? 'Related hosts and services' : 'Busiest hosts and services'}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {others.map((v) => {
                  const value = `${v.kind}:${v.value}`
                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setFilter(value)}
                      className={cn(
                        'inline-flex h-8 items-center gap-2 rounded-full border px-3 text-[12px] transition-colors',
                        filter === value
                          ? 'border-brand bg-brand-soft text-brand-strong'
                          : 'border-line-strong text-text hover:bg-raised bg-white',
                      )}
                    >
                      <span className="font-mono">{value}</span>
                      <span className="text-faint">{count(v.count)}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          ) : null}

          <div>
            <div className="text-faint pb-2 text-[12px] font-medium">Datadog filter</div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="border-line-strong focus-within:border-brand flex h-10 min-w-[260px] flex-1 items-center gap-2 rounded-full border bg-white pr-2 pl-4">
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="host:name* or service:name"
                  spellCheck={false}
                  className="placeholder:text-faint min-w-0 flex-1 bg-transparent font-mono text-[12.5px] outline-none"
                />
                {logs === 'busy' ? (
                  <Spinner className="text-faint size-3.5" />
                ) : typeof logs === 'number' ? (
                  <span
                    className={cn(
                      'shrink-0 rounded-full px-2.5 py-0.5 text-[11.5px] font-medium',
                      logs ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn',
                    )}
                  >
                    {logs ? `${count(logs)} logs / 24h` : 'No logs in 24h'}
                  </span>
                ) : null}
              </div>
              <Button
                variant="primary"
                size="lg"
                disabled={!filter.trim() || saving}
                onClick={() => void save()}
              >
                {saving ? <Spinner className="size-4" /> : null} Save and open Health
              </Button>
            </div>
            <div className="text-faint mt-2 px-1 text-[11.5px]">
              Combine tags with spaces, e.g. host:acme-app-* env:prod. A trailing * matches a
              prefix.
            </div>
          </div>
          {error ? <div className="text-danger text-[12.5px]">{error}</div> : null}
        </div>
      </Card>

      <div>
        <div className="text-faint px-1 pb-3 text-[12px] font-medium">
          Once matched, Health shows
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {PREVIEW.map((item) => (
            <Card key={item.title} className="p-4">
              <IconBadge icon={item.icon} size="sm" />
              <div className="text-fg mt-3 text-[13px] font-semibold">{item.title}</div>
              <div className="text-muted mt-1 text-[12px] leading-relaxed">{item.text}</div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}

export function HealthPage() {
  const { status, setStatus } = useDatadog()
  const { instances } = useInstances()
  const signedIn = useMemo(() => {
    const byHost = new Map<string, Instance>()
    const valid = (instances ?? []).filter((i) => i.valid)
    for (const i of [...valid].sort(
      (a, b) => Number(Boolean(a.tenant)) - Number(Boolean(b.tenant)),
    ))
      if (!byHost.has(i.host)) byHost.set(i.host, i)
    return [...byHost.values()].sort((a, b) => a.host.localeCompare(b.host))
  }, [instances])
  const [alias, setAlias] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const [range, setRange] = useState<Range>('24h')
  const [report, setReport] = useState<InstanceHealth>()
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!instances || signedIn.some((i) => i.alias === alias)) return
    const host = instances.find((i) => i.alias === alias)?.host
    setAlias((signedIn.find((i) => i.host === host) ?? signedIn[0])?.alias ?? '')
  }, [instances])
  useEffect(() => {
    if (alias) localStorage.setItem(INSTANCE_KEY, alias)
  }, [alias])

  const current = signedIn.find((i) => i.alias === alias)
  const label = current?.host ?? ''

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

  const ask = () =>
    openDraft({
      prompt: `Check the health of ${label} over the last ${RANGE_WORDS[range]}. Use Datadog: alerting monitors, events such as deploys and restarts, error logs grouped by pattern, and server metrics. Line them up with failed OneVizion processes in the same window. Tell me what changed or is failing, the likely cause, and what to do.`,
      instance: alias,
    })

  const actions = status?.connected ? (
    <>
      <div className="w-[260px]">
        <Select
          className="w-full"
          value={alias}
          onChange={setAlias}
          placeholder={instances ? 'No signed-in instance' : 'Loading...'}
          options={signedIn.map((i) => ({ value: i.alias, label: i.host }))}
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
        {loading ? <Spinner className="size-3.5" /> : <ArrowPathIcon className="size-3.5" />}
      </Button>
      <Button variant="primary" disabled={!alias} onClick={ask}>
        <SparklesIcon className="size-3.5" /> Ask the agent
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
        <EmptyState
          badge={<DatadogBadge size="lg" />}
          title="Connect Datadog"
          action={
            <Button variant="primary" onClick={() => setConnecting(true)}>
              Connect Datadog
            </Button>
          }
        >
          See each instance's alerting monitors, error logs, slow endpoints and server metrics next
          to its failed OneVizion processes. The agent can then read Datadog in runs too. Read-only,
          with your own keys.
        </EmptyState>
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
      <>
        {report.pagerduty ? (
          <div className="mx-auto w-full max-w-[920px] px-6 pt-6">
            <Incidents data={report.pagerduty} range={range} />
          </div>
        ) : null}
        <MatchInstance host={label} alias={alias} status={status} onSaved={setStatus} />
      </>
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
        <Report report={report} status={status} label={label} range={range} />
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
