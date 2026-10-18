import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  CheckCircle as CheckCircleIcon,
  CaretRight as ChevronRightIcon,
  Warning as ExclamationTriangleIcon,
  Lock as LockClosedIcon,
  ShieldWarning as ShieldExclamationIcon,
  Sparkle as SparklesIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useState } from 'react'
import type {
  HealthDatabaseMetricKey,
  HealthMeta,
  HealthPoint,
  HealthSection,
  HealthSections,
  HealthServer,
  PagerDutyIncident,
  PagerDutyIncidentDetail,
} from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { type BadgeTone, Card, IconBadge, Skeleton } from '@/components/common/ui'
import { DATADOG_PURPLE } from '@/components/integrations/Datadog'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { openDraft } from '@/lib/draft'
import { shortHost } from '@/lib/servers'
import { MINUTE_MS } from '@/lib/time'
import { type Lane, Sparkline, Timeline } from './charts'
import {
  count,
  duration,
  fmt,
  RANGE_WORDS,
  type Range,
  ready,
  type Slot,
  type Slots,
  span,
  total,
  utcMs,
} from './data'

const BLUE = '#42a5f5'
const RED = '#e53935'
const ORANGE = '#fb8c00'

const ERROR_SPIKE_PERCENT = 50
const ERROR_SPIKE_MIN = 10
const SLOW_P95_MS = 10_000
const SLUGGISH_P95_MS = 3000
const FAILED_RUNS_DANGER = 50
const INCIDENT_ROWS = 8
const MONITOR_ROWS = 8
const TOP_ERROR_ROWS = 6
const EVENT_ROWS = 6
const DETAIL_TIMELINE_ROWS = 6
const MIN_BAR_PERCENT = 3

type Tone = 'danger' | 'warn' | null

const SERVER_CPU = { warn: 65, danger: 85 }
const SERVER_FREE_MEMORY = { warn: 20, danger: 10 }
const SERVER_DISK = { warn: 80, danger: 90 }
const SERVER_LOAD = { warn: 1, danger: 1.5 }

const DB_CPU = { warn: 65, danger: 85 }
const DB_STORAGE = { warn: 80, danger: 90 }
const DB_SESSIONS = { warn: 70, danger: 90 }
const DB_TABLESPACE = { warn: 80, danger: 90 }

function atLeast(limits: { warn: number; danger: number }): (v: number) => Tone {
  return (v) => (v >= limits.danger ? 'danger' : v >= limits.warn ? 'warn' : null)
}

function atMost(limits: { warn: number; danger: number }): (v: number) => Tone {
  return (v) => (v <= limits.danger ? 'danger' : v <= limits.warn ? 'warn' : null)
}

const THRESHOLDS: Record<string, { title: string; unit: string; tone: (v: number) => Tone }> = {
  cpu: { title: 'CPU', unit: '%', tone: atLeast(SERVER_CPU) },
  memory: { title: 'Memory free', unit: '%', tone: atMost(SERVER_FREE_MEMORY) },
  disk: { title: 'Disk used', unit: '%', tone: atLeast(SERVER_DISK) },
  load: { title: 'Load', unit: '', tone: atLeast(SERVER_LOAD) },
  heap: { title: 'JVM heap', unit: 'B', tone: () => null },
}

const percent = (v: number) => fmt(v, '%')

const DATABASE_METRICS: Record<
  HealthDatabaseMetricKey,
  { title: string; format: (v: number) => string; tone: (v: number) => Tone }
> = {
  cpu: { title: 'CPU', format: percent, tone: atLeast(DB_CPU) },
  memory: { title: 'Free memory', format: (v) => fmt(v, 'B'), tone: () => null },
  storage: { title: 'Storage used', format: percent, tone: atLeast(DB_STORAGE) },
  connections: { title: 'Connections', format: count, tone: () => null },
  readLatency: { title: 'Read latency', format: duration, tone: () => null },
  writeLatency: { title: 'Write latency', format: duration, tone: () => null },
  sessions: { title: 'Session limit', format: percent, tone: atLeast(DB_SESSIONS) },
  tablespace: { title: 'Tablespace', format: percent, tone: atLeast(DB_TABLESPACE) },
}

const TONE_TEXT: Record<'danger' | 'warn', string> = { danger: 'text-danger', warn: 'text-warn' }
const TONE_LINE: Record<'danger' | 'warn' | 'ok', string> = {
  danger: RED,
  warn: ORANGE,
  ok: DATADOG_PURPLE,
}

const INCIDENT_DOT: Record<string, string> = {
  triggered: 'bg-danger',
  acknowledged: 'bg-warn',
  resolved: 'bg-ok',
}

const MONITOR_DOT: Record<string, string> = {
  Alert: 'bg-danger',
  Warn: 'bg-warn',
  'No Data': 'bg-line-strong',
  OK: 'bg-ok',
}

export type Context = { meta: HealthMeta; label: string; alias: string; range: Range; slots: Slots }

function ask(ctx: Context, prompt: string) {
  openDraft({
    instance: ctx.alias,
    prompt: `${prompt} Instance ${ctx.label}, last ${RANGE_WORDS[ctx.range]}.`,
  })
}

function Panel({
  title,
  hint,
  link,
  linkLabel = 'Datadog',
  onAsk,
  className,
  children,
}: {
  title: ReactNode
  hint?: ReactNode
  link?: string
  linkLabel?: string
  onAsk?: () => void
  className?: string
  children: ReactNode
}) {
  return (
    <Card className={cn('flex flex-col p-5', className)}>
      <div className="flex items-start gap-2 pb-3">
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13.5px] font-semibold">{title}</div>
          {hint ? <div className="text-muted mt-0.5 text-[12px]">{hint}</div> : null}
        </div>
        {onAsk ? (
          <button
            type="button"
            onClick={onAsk}
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
            className="text-brand-strong hover:bg-brand-soft inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium"
          >
            {linkLabel} <ArrowTopRightOnSquareIcon className="size-3" />
          </a>
        ) : null}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </Card>
  )
}

function Quiet({ children }: { children: ReactNode }) {
  return (
    <div className="text-muted flex items-center gap-2 text-[12.5px]">
      <CheckCircleIcon className="text-ok size-4 shrink-0" />
      {children}
    </div>
  )
}

function RowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-3.5', i % 2 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}

function Body<K extends HealthSection>({
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
  if (slot.state === 'unavailable')
    return (
      <div className="text-muted flex items-start gap-2 text-[12.5px]">
        <LockClosedIcon className="text-faint mt-0.5 size-3.5 shrink-0" />
        {slot.reason}
      </div>
    )

  return <>{children(slot.value)}</>
}

type Signal = { tone: 'danger' | 'warn'; text: string }

function openFirst(incidents: HealthSections['incidents']): PagerDutyIncident[] {
  const openIds = new Set((incidents.open ?? []).map((i) => i.id))
  return [
    ...(incidents.open ?? []),
    ...(incidents.incidents ?? []).filter((i) => !openIds.has(i.id)),
  ]
}

function errorChange(logs?: HealthSections['logs']): number | null {
  if (!logs?.previousErrors) return null
  return Math.round(((total(logs.errorSeries) - logs.previousErrors) / logs.previousErrors) * 100)
}

function busiest(servers?: HealthServer[]) {
  const withCpu = (servers ?? []).filter((s) => s.metrics.cpu)
  return withCpu.sort((a, b) => b.metrics.cpu!.latest - a.metrics.cpu!.latest)[0]
}

function signals(slots: Slots): Signal[] {
  const out: Signal[] = []
  const incidents = ready(slots.incidents)
  const open = incidents?.open ?? []
  const triggered = open.filter((i) => i.status === 'triggered').length
  if (triggered)
    out.push({ tone: 'danger', text: `${triggered} incident${triggered > 1 ? 's' : ''} triggered` })

  if (open.length - triggered)
    out.push({ tone: 'warn', text: `${open.length - triggered} incident(s) acknowledged` })

  const monitors = ready(slots.monitors)?.monitors ?? []
  const alerts = monitors.filter((m) => m.state === 'Alert').length
  if (alerts)
    out.push({ tone: 'danger', text: `${alerts} monitor${alerts > 1 ? 's' : ''} alerting` })

  const logs = ready(slots.logs)
  const change = errorChange(logs)
  if (
    logs &&
    change !== null &&
    change > ERROR_SPIKE_PERCENT &&
    total(logs.errorSeries) >= ERROR_SPIKE_MIN
  )
    out.push({ tone: 'warn', text: `Error logs up ${change}%` })

  const slowest = ready(slots.traffic)?.slowEndpoints[0]
  if (slowest && slowest.p95Ms >= SLOW_P95_MS)
    out.push({ tone: 'warn', text: `Slowest endpoint ${duration(slowest.p95Ms)} p95` })

  const failed = total((ready(slots.onevizion)?.byType ?? []).map((f) => ({ v: f.count })))
  if (failed)
    out.push({
      tone: failed >= FAILED_RUNS_DANGER ? 'danger' : 'warn',
      text: `${count(failed)} failed runs`,
    })

  for (const server of ready(slots.servers)?.servers ?? [])
    for (const [key, metric] of Object.entries(server.metrics)) {
      const tone = THRESHOLDS[key].tone(metric.latest)
      if (tone)
        out.push({
          tone,
          text: `${shortHost(server.host)} ${THRESHOLDS[key].title.toLowerCase()} ${fmt(metric.latest, THRESHOLDS[key].unit)}`,
        })
    }

  for (const db of ready(slots.database)?.databases ?? [])
    for (const [key, metric] of Object.entries(db.metrics)) {
      const spec = DATABASE_METRICS[key as HealthDatabaseMetricKey]
      const tone = spec.tone(metric.latest)
      if (tone)
        out.push({
          tone,
          text: `${db.id} ${spec.title.toLowerCase()} ${spec.format(metric.latest)}`,
        })
    }

  return out
}

function Stat<K extends HealthSection>({
  label,
  slot,
  value,
}: {
  label: string
  slot: Slot<K>
  value: (v: HealthSections[K]) => { main: ReactNode; sub?: ReactNode; tone?: Tone }
}) {
  const showSkeleton = useSkeleton(slot.state === 'loading')

  const shown =
    slot.state === 'ready'
      ? value(slot.value)
      : {
          main: '-',
          sub:
            slot.state === 'unavailable'
              ? 'No access'
              : slot.state === 'error'
                ? 'Failed'
                : undefined,
        }

  return (
    <div className="bg-raised min-w-0 rounded-2xl px-4 py-3">
      <div className="text-muted truncate text-[12px]">{label}</div>
      {showSkeleton || slot.state === 'loading' ? (
        <>
          <Skeleton className="mt-2 h-5 w-12" />
          <Skeleton className="mt-2 h-2.5 w-20" />
        </>
      ) : (
        <>
          <div
            className={cn(
              'mt-1 truncate text-[20px] leading-tight font-semibold tabular-nums',
              shown.tone ? TONE_TEXT[shown.tone] : 'text-fg',
            )}
          >
            {shown.main}
          </div>
          <div className="text-faint mt-0.5 truncate text-[11.5px]">{shown.sub ?? '\u00a0'}</div>
        </>
      )}
    </div>
  )
}

export function Summary({ ctx, busy }: { ctx: Context; busy: boolean }) {
  const { slots } = ctx
  const found = signals(slots)

  const verdict: { tone: BadgeTone; title: string; icon: typeof CheckCircleIcon } = found.some(
    (s) => s.tone === 'danger',
  )
    ? { tone: 'danger', title: 'Needs attention', icon: ShieldExclamationIcon }
    : found.length
      ? { tone: 'warn', title: 'Worth a look', icon: ExclamationTriangleIcon }
      : { tone: 'ok', title: busy ? 'Checking' : 'Healthy', icon: CheckCircleIcon }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-4">
        <IconBadge
          icon={verdict.icon}
          tone={busy && !found.length ? 'neutral' : verdict.tone}
          size="lg"
        />
        <div className="min-w-[240px] flex-1">
          <div className="text-fg text-[17px] font-semibold">{verdict.title}</div>
          <div className="text-muted mt-0.5 text-[12.5px]">
            {ctx.label} over the last {RANGE_WORDS[ctx.range]}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {found.map((s) => (
              <span
                key={s.text}
                className="bg-raised text-text inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[12px]"
              >
                <span
                  className={cn(
                    'size-1.5 rounded-full',
                    s.tone === 'danger' ? 'bg-danger' : 'bg-warn',
                  )}
                />
                {s.text}
              </span>
            ))}
            {busy ? <Skeleton className="h-7 w-32 rounded-full" /> : null}
            {!busy && !found.length ? (
              <span className="bg-raised text-text inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[12px]">
                <span className="bg-ok size-1.5 rounded-full" /> No incidents, alerts, error spikes
                or failed runs
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Open incidents"
          slot={slots.incidents}
          value={(v) => {
            const open = v.open ?? []

            return {
              main: open.length,
              sub: `${(v.incidents ?? []).length} in this window`,
              tone: open.some((i) => i.status === 'triggered')
                ? 'danger'
                : open.length
                  ? 'warn'
                  : null,
            }
          }}
        />
        <Stat
          label="Alerting monitors"
          slot={slots.monitors}
          value={(v) => {
            const alerting = v.monitors.filter((m) => m.state !== 'OK')

            return {
              main: alerting.length,
              sub: v.monitors.length ? `of ${v.monitors.length} watching` : 'None set up',
              tone: alerting.some((m) => m.state === 'Alert')
                ? 'danger'
                : alerting.length
                  ? 'warn'
                  : null,
            }
          }}
        />
        <Stat
          label="Error logs"
          slot={slots.logs}
          value={(v) => {
            const change = errorChange(v)

            return {
              main: count(total(v.errorSeries)),
              sub:
                change === null
                  ? 'No earlier data'
                  : `${change > 0 ? '+' : ''}${change}% vs previous`,
              tone: change !== null && change > ERROR_SPIKE_PERCENT ? 'warn' : null,
            }
          }}
        />
        <Stat
          label="Peak p95"
          slot={slots.traffic}
          value={(v) => {
            const peak = Math.max(0, ...v.traffic.p95Ms.map((p) => p.v))
            return {
              main: peak ? duration(peak) : '-',
              sub: `${count(total(v.traffic.requests))} requests`,
              tone: peak >= SLOW_P95_MS ? 'danger' : peak >= SLUGGISH_P95_MS ? 'warn' : null,
            }
          }}
        />
        <Stat
          label="Failed runs"
          slot={slots.onevizion}
          value={(v) => {
            const failed = v.byType.reduce((sum, f) => sum + f.count, 0)
            return {
              main: count(failed),
              sub: v.byType[0] ? `Most: ${v.byType[0].type}` : 'OneVizion processes',
              tone: failed >= FAILED_RUNS_DANGER ? 'danger' : failed ? 'warn' : null,
            }
          }}
        />
        <Stat
          label="Busiest server"
          slot={slots.servers}
          value={(v) => {
            const top = busiest(v.servers)

            return top
              ? {
                  main: fmt(top.metrics.cpu!.latest, '%'),
                  sub: `${shortHost(top.host)} CPU`,
                  tone: THRESHOLDS.cpu.tone(top.metrics.cpu!.latest),
                }
              : { main: '-', sub: 'No metrics' }
          }}
        />
      </div>
    </Card>
  )
}

export function TimelineCard({ ctx }: { ctx: Context }) {
  const { slots, meta } = ctx
  const traffic = ready(slots.traffic)
  const logs = ready(slots.logs)
  const incidents = ready(slots.incidents)
  const events = ready(slots.events)
  const failures = ready(slots.onevizion)
  const hasTraffic = Boolean(traffic?.traffic.requests.some((p) => p.v > 0))
  const loading = (['traffic', 'logs', 'incidents', 'events', 'onevizion'] as const).some(
    (s) => slots[s].state === 'loading',
  )
  const showSkeleton = useSkeleton(loading && !traffic && !logs)

  const lanes: Lane[] = [
    {
      label: 'Incidents',
      color: RED,
      items: (incidents ? openFirst(incidents) : []).map((i) => ({
        t: utcMs(i.created),
        title: `#${i.number} ${i.title}`,
      })),
    },
    {
      label: 'Events',
      color: DATADOG_PURPLE,
      items: (events?.events ?? []).map((e) => ({ t: utcMs(e.time), title: e.title || e.message })),
    },
    {
      label: 'Failed runs',
      color: ORANGE,
      items: (failures?.failures ?? []).map((f) => ({
        t: utcMs(f.at) - failures!.utcOffsetMinutes * MINUTE_MS,
        title: f.type,
      })),
    },
  ]

  return (
    <Panel
      title="Timeline"
      hint="What lined up with what: traffic, latency and errors, with incidents, deploys and failed runs below"
      link={meta.links.apm}
      onAsk={() =>
        ask(
          ctx,
          'Walk the timeline of this instance: traffic, p95 latency, error logs, incidents, Datadog events such as deploys and restarts, and failed OneVizion processes. Find what changed together, when, and the most likely cause.',
        )
      }
    >
      {showSkeleton ? (
        <Skeleton className="h-[230px] w-full rounded-2xl" />
      ) : (
        <Timeline
          from={meta.from}
          to={meta.to}
          range={ctx.range}
          bars={
            hasTraffic
              ? {
                  label: 'Requests',
                  color: BLUE,
                  points: traffic!.traffic.requests,
                  combine: 'sum',
                  format: count,
                }
              : logs
                ? {
                    label: 'Log lines',
                    color: BLUE,
                    points: logs.logSeries,
                    combine: 'sum',
                    format: count,
                  }
                : undefined
          }
          lines={[
            ...(hasTraffic
              ? [
                  {
                    label: 'p95',
                    color: DATADOG_PURPLE,
                    points: traffic!.traffic.p95Ms,
                    combine: 'max' as const,
                    format: duration,
                  },
                ]
              : []),
            ...(logs
              ? [
                  {
                    label: 'Error logs',
                    color: RED,
                    points: logs.errorSeries,
                    combine: 'sum' as const,
                    format: count,
                  },
                ]
              : []),
          ]}
          lanes={lanes}
        />
      )}
    </Panel>
  )
}

function shortTime(value: string): string {
  return new Date(utcMs(value)).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function IncidentDetail({ incident, ctx }: { incident: PagerDutyIncident; ctx: Context }) {
  const [detail, setDetail] = useState<PagerDutyIncidentDetail>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    api
      .pagerdutyIncident(incident.id)
      .then(setDetail)
      .catch((e: Error) => setError(e.message))
  }, [incident.id])

  return (
    <div className="bg-raised mx-1 mt-1 mb-2 space-y-3 rounded-2xl px-4 py-3 text-[12.5px]">
      <div className="text-fg break-words">{incident.title}</div>
      {error ? <div className="text-danger">{error}</div> : null}
      {!detail && !error ? <RowsSkeleton rows={3} /> : null}
      {detail?.alerts[0]?.details ? (
        <pre className="text-text max-h-[180px] scrollbar-thin overflow-auto rounded-2xl bg-white px-3 py-2 font-mono text-[11px] whitespace-pre-wrap">
          {detail.alerts[0].details}
        </pre>
      ) : null}
      {detail?.timeline.length ? (
        <div className="space-y-1">
          {detail.timeline.slice(-DETAIL_TIMELINE_ROWS).map((e, i) => (
            <div key={i} className="text-muted flex gap-3">
              <span className="text-faint w-32 shrink-0 whitespace-nowrap">
                {shortTime(e.time)}
              </span>
              <span className="min-w-0 truncate">{e.summary}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() =>
            ask(
              ctx,
              `Review PagerDuty incident #${incident.number} ("${incident.title}"): read it, find the cause in Datadog and on the instance, and say what to do.`,
            )
          }
          className="bg-brand text-on-brand hover:bg-brand-strong inline-flex h-7 items-center gap-1 rounded-full px-3 text-[12px] font-medium"
        >
          <SparklesIcon className="size-3.5" /> Ask the agent
        </button>
        <a
          href={incident.url}
          target="_blank"
          rel="noreferrer"
          className="text-brand-strong inline-flex h-7 items-center gap-1 rounded-full bg-white px-3 text-[12px] font-medium"
        >
          Open in PagerDuty <ArrowTopRightOnSquareIcon className="size-3" />
        </a>
      </div>
    </div>
  )
}

export function IncidentsCard({ ctx }: { ctx: Context }) {
  const [open, setOpen] = useState<string>()
  const data = ready(ctx.slots.incidents)

  return (
    <Panel
      title="Incidents"
      hint={
        data?.oncall?.length
          ? `On call now: ${data.oncall.map((o) => o.user).join(', ')}`
          : undefined
      }
      link={data?.webUrl ? `${data.webUrl}/incidents` : undefined}
      linkLabel="PagerDuty"
      onAsk={() =>
        ask(
          ctx,
          'Review the open and recent PagerDuty incidents for this instance and what caused them.',
        )
      }
    >
      <Body slot={ctx.slots.incidents}>
        {(v) => {
          const rows = openFirst(v).slice(0, INCIDENT_ROWS)
          if (Object.keys(v.errors).length)
            return <div className="text-danger text-[12.5px]">{Object.values(v.errors)[0]}</div>
          if (!rows.length) return <Quiet>No incidents in the last {RANGE_WORDS[ctx.range]}.</Quiet>

          return (
            <div className="-mx-2">
              {rows.map((i) => {
                const resolved = i.status === 'resolved'
                const age = resolved
                  ? `resolved after ${span(utcMs(i.created), utcMs(i.changed))}`
                  : `open ${span(utcMs(i.created), Date.now())}`

                return (
                  <div key={i.id}>
                    <button
                      type="button"
                      onClick={() => setOpen(open === i.id ? undefined : i.id)}
                      className="hover:bg-raised flex w-full items-center gap-3 rounded-full px-3 py-2 text-left"
                    >
                      <span
                        className={cn('size-2 shrink-0 rounded-full', INCIDENT_DOT[i.status])}
                      />
                      <span className="text-faint w-14 shrink-0 text-[12px] tabular-nums">
                        #{i.number}
                      </span>
                      <span className="text-fg min-w-0 flex-1 truncate text-[12.5px]">
                        {i.title}
                      </span>
                      {i.service ? (
                        <span className="text-muted hidden max-w-[180px] shrink-0 truncate text-[11.5px] lg:block">
                          {i.service}
                        </span>
                      ) : null}
                      {i.urgency === 'high' ? (
                        <span className="bg-danger-soft text-danger shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium">
                          high
                        </span>
                      ) : null}
                      <span className="text-faint w-36 shrink-0 text-right text-[11.5px]">
                        {age}
                      </span>
                      <ChevronRightIcon
                        className={cn(
                          'text-faint size-3.5 shrink-0 transition-transform',
                          open === i.id && 'rotate-90',
                        )}
                      />
                    </button>
                    {open === i.id ? <IncidentDetail incident={i} ctx={ctx} /> : null}
                  </div>
                )
              })}
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

export function ServersCard({ ctx }: { ctx: Context }) {
  const keys = Object.keys(THRESHOLDS)

  return (
    <Panel
      title="Servers"
      hint="Each metric over the window, latest value on the right"
      link={ctx.meta.links.metrics}
      onAsk={() =>
        ask(
          ctx,
          'Compare the servers of this instance: CPU, memory, disk, load and JVM heap. Say which one stands out and why.',
        )
      }
    >
      <Body slot={ctx.slots.servers} skeleton={<RowsSkeleton rows={3} />}>
        {(v) => {
          const shown = keys.filter((k) =>
            v.servers.some((s) => s.metrics[k as keyof HealthServer['metrics']]),
          )

          if (!v.servers.length) return <Quiet>No server metrics in this window.</Quiet>

          return (
            <div className="scrollbar-thin overflow-x-auto">
              <table className="w-full min-w-[720px] text-[12.5px]">
                <thead>
                  <tr className="text-faint text-left text-[11.5px]">
                    <th className="pb-2 font-medium">Server</th>
                    {shown.map((k) => (
                      <th key={k} className="pb-2 pl-4 font-medium">
                        {THRESHOLDS[k].title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-line divide-y">
                  {v.servers.map((s) => (
                    <tr key={s.host}>
                      <td className="py-2.5 pr-4 whitespace-nowrap" title={s.host}>
                        <span className="bg-brand-soft text-brand-strong mr-2 rounded-full px-1.5 py-0.5 text-[10.5px] font-medium">
                          {s.role}
                        </span>
                        <span className="text-fg">{shortHost(s.host)}</span>
                      </td>
                      {shown.map((k) => {
                        const m = s.metrics[k as keyof HealthServer['metrics']]

                        return (
                          <MetricCell
                            key={k}
                            metric={m}
                            tone={m ? THRESHOLDS[k].tone(m.latest) : null}
                            text={m ? fmt(m.latest, THRESHOLDS[k].unit) : ''}
                          />
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

function MetricCell({
  metric,
  tone,
  text,
}: {
  metric?: { points: HealthPoint[] }
  tone: Tone
  text: string
}) {
  return (
    <td className="py-2.5 pl-4">
      {metric ? (
        <div className="flex items-center gap-2">
          <Sparkline points={metric.points} color={TONE_LINE[tone ?? 'ok']} className="w-20" />
          <span
            className={cn(
              'w-14 shrink-0 text-right tabular-nums',
              tone ? `${TONE_TEXT[tone]} font-semibold` : 'text-text',
            )}
          >
            {text}
          </span>
        </div>
      ) : (
        <span className="text-faint">-</span>
      )}
    </td>
  )
}

export function DatabaseCard({ ctx }: { ctx: Context }) {
  const keys = Object.keys(DATABASE_METRICS) as HealthDatabaseMetricKey[]

  return (
    <Panel
      title="Database"
      hint="RDS and Oracle metrics over the window, latest value on the right"
      onAsk={() =>
        ask(
          ctx,
          'Check the database of this instance: CPU, free memory, storage, connections, read and write latency, Oracle session limit and tablespace use, and any database monitors or incidents. Say what stands out and why.',
        )
      }
    >
      <Body slot={ctx.slots.database} skeleton={<RowsSkeleton rows={2} />}>
        {(v) => {
          const shown = keys.filter((k) => v.databases.some((d) => d.metrics[k]))
          if (!v.databases.length) return <Quiet>No database metrics in this window.</Quiet>

          return (
            <div className="scrollbar-thin overflow-x-auto">
              <table className="w-full min-w-[960px] text-[12.5px]">
                <thead>
                  <tr className="text-faint text-left text-[11.5px]">
                    <th className="pb-2 font-medium">Database</th>
                    {shown.map((k) => (
                      <th key={k} className="pb-2 pl-4 font-medium">
                        {DATABASE_METRICS[k].title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-line divide-y">
                  {v.databases.map((d) => (
                    <tr key={d.id}>
                      <td className="py-2.5 pr-4 whitespace-nowrap" title={d.endpoint || d.id}>
                        {d.engine ? (
                          <span className="bg-brand-soft text-brand-strong mr-2 rounded-full px-1.5 py-0.5 text-[10.5px] font-medium">
                            {d.engine}
                          </span>
                        ) : null}
                        <span className="text-fg">{d.id}</span>
                      </td>
                      {shown.map((k) => {
                        const m = d.metrics[k]

                        return (
                          <MetricCell
                            key={k}
                            metric={m}
                            tone={m ? DATABASE_METRICS[k].tone(m.latest) : null}
                            text={m ? DATABASE_METRICS[k].format(m.latest) : ''}
                          />
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

function Bar({ value, max, tone }: { value: number; max: number; tone: string }) {
  return (
    <div className="bg-raised mt-1.5 h-1.5 overflow-hidden rounded-full">
      <div
        className={cn('h-full rounded-full', tone)}
        style={{ width: `${Math.max(MIN_BAR_PERCENT, (value / max) * 100)}%` }}
      />
    </div>
  )
}

export function TopErrorsCard({ ctx }: { ctx: Context }) {
  return (
    <Panel
      title="Top errors"
      hint="Error logs grouped by message"
      link={ctx.meta.links.logs}
      onAsk={() =>
        ask(ctx, 'Explain the top error log groups of this instance and what causes them.')
      }
    >
      <Body slot={ctx.slots.logs}>
        {(v) => {
          if (!v.topErrors.length) return <Quiet>No error logs.</Quiet>

          const max = Math.max(...v.topErrors.map((e) => e.count))

          return (
            <div className="space-y-3">
              {v.topErrors.slice(0, TOP_ERROR_ROWS).map((e) => (
                <div key={e.pattern} title={e.example}>
                  <div className="flex items-baseline gap-3">
                    <span className="text-text min-w-0 flex-1 truncate font-mono text-[11.5px]">
                      {e.pattern}
                    </span>
                    <span className="text-fg shrink-0 text-[12px] font-semibold tabular-nums">
                      {count(e.count)}
                    </span>
                  </div>
                  <Bar value={e.count} max={max} tone="bg-danger" />
                </div>
              ))}
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

export function FailedRunsCard({ ctx }: { ctx: Context }) {
  return (
    <Panel
      title="Failed OneVizion runs"
      hint="Processes that ended with errors, by type"
      onAsk={() =>
        ask(
          ctx,
          'Which OneVizion processes failed on this instance (rules, imports, reports, modules), and why? Group them by cause.',
        )
      }
    >
      <Body slot={ctx.slots.onevizion}>
        {(v) => {
          if (!v.byType.length) return <Quiet>No failed processes in this window.</Quiet>

          const max = Math.max(...v.byType.map((f) => f.count))

          return (
            <div className="space-y-3">
              {v.byType.map((f) => (
                <div key={f.type}>
                  <div className="flex items-baseline gap-3 text-[12.5px]">
                    <span className="text-fg min-w-0 flex-1 truncate font-medium">{f.type}</span>
                    <span className="text-faint shrink-0 text-[11.5px]">last {f.last}</span>
                    <span className="text-fg w-10 shrink-0 text-right font-semibold tabular-nums">
                      {count(f.count)}
                    </span>
                  </div>
                  <Bar value={f.count} max={max} tone="bg-warn" />
                </div>
              ))}
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

export function SlowEndpointsCard({ ctx }: { ctx: Context }) {
  return (
    <Panel
      title="Slowest endpoints"
      hint="p95 response time"
      link={ctx.meta.links.apm}
      onAsk={() =>
        ask(
          ctx,
          'Why are the slowest endpoints of this instance slow? Use APM traces and the instance configuration.',
        )
      }
    >
      <Body slot={ctx.slots.traffic}>
        {(v) => {
          if (!v.slowEndpoints.length) return <Quiet>No traces in this window.</Quiet>

          const max = Math.max(...v.slowEndpoints.map((s) => s.p95Ms))

          return (
            <div className="space-y-3">
              {v.slowEndpoints.map((s) => (
                <div key={s.resource} title={s.resource}>
                  <div className="flex items-baseline gap-3">
                    <span className="text-fg min-w-0 flex-1 truncate font-mono text-[11.5px]">
                      {s.resource}
                    </span>
                    <span className="text-faint shrink-0 text-[11.5px]">
                      {count(s.count)} calls
                    </span>
                    <span className="text-fg w-12 shrink-0 text-right text-[12px] font-semibold tabular-nums">
                      {duration(s.p95Ms)}
                    </span>
                  </div>
                  <Bar
                    value={s.p95Ms}
                    max={max}
                    tone={
                      s.p95Ms >= SLOW_P95_MS
                        ? 'bg-danger'
                        : s.p95Ms >= SLUGGISH_P95_MS
                          ? 'bg-warn'
                          : 'bg-brand'
                    }
                  />
                </div>
              ))}
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

export function MonitorsCard({ ctx }: { ctx: Context }) {
  return (
    <Panel title="Monitors" hint="Datadog monitors on these servers" link={ctx.meta.links.monitors}>
      <Body slot={ctx.slots.monitors}>
        {(v) => {
          const alerting = v.monitors.filter((m) => m.state !== 'OK')
          if (!v.monitors.length) return <Quiet>No monitors watch this instance.</Quiet>
          if (!alerting.length) return <Quiet>All {v.monitors.length} monitors OK.</Quiet>

          return (
            <div className="-mx-2 space-y-0.5">
              {alerting.slice(0, MONITOR_ROWS).map((m) => (
                <a
                  key={m.id}
                  href={`${ctx.meta.appUrl}/monitors/${m.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:bg-raised flex h-8 items-center gap-2.5 rounded-full px-2.5"
                >
                  <span className={cn('size-2 shrink-0 rounded-full', MONITOR_DOT[m.state])} />
                  <span className="text-fg min-w-0 flex-1 truncate text-[12.5px]">{m.name}</span>
                </a>
              ))}
            </div>
          )
        }}
      </Body>
    </Panel>
  )
}

export function EventsCard({ ctx }: { ctx: Context }) {
  return (
    <Panel title="Events" hint="Deploys, restarts and alerts" link={ctx.meta.links.events}>
      <Body slot={ctx.slots.events}>
        {(v) =>
          v.events.length ? (
            <div className="space-y-2.5">
              {v.events.slice(0, EVENT_ROWS).map((e, i) => (
                <div key={i} className="min-w-0">
                  <div className="text-fg truncate text-[12.5px]">{e.title || e.message}</div>
                  <div className="text-faint text-[11px]">{shortTime(e.time)}</div>
                </div>
              ))}
            </div>
          ) : (
            <Quiet>No deploys, restarts or other events.</Quiet>
          )
        }
      </Body>
    </Panel>
  )
}
