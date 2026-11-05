import type {
  HealthDatabaseMetricKey,
  HealthMeta,
  HealthPoint,
  HealthSections,
  HealthServer,
  HealthServerMetric,
  PagerDutyIncident,
} from '@shared/types.ts'
import { shortHost } from '@/lib/servers'
import { count, duration, fmt, type Slot, type Slots, total, whenOf } from './data'
import { plural } from '@/lib/text'

export type Level = 'danger' | 'warn' | 'ok'
export type CheckState = Level | 'off' | 'loading'

export const SLOW_P95_MS = 10_000
export const SLUGGISH_P95_MS = 3000
const ERROR_RATE_WARN = 1
const ERROR_RATE_DANGER = 5
const MIN_REQUESTS_FOR_RATE = 100
const PERCENT = 100
const STALE_INTERVALS = 3

type Limits = { warn: number; danger: number }

const CPU_LIMITS: Limits = { warn: 65, danger: 85 }
const FILL_LIMITS: Limits = { warn: 80, danger: 90 }
const SESSION_LIMITS: Limits = { warn: 70, danger: 90 }
const LOAD_LIMITS: Limits = { warn: 1, danger: 1.5 }

export type Gauge = {
  title: string
  format: (v: number) => string
  level: (v: number) => Level
  limits?: Limits
  percent: boolean
  series: (m: HealthServerMetric) => HealthPoint[]
  read: (m: HealthServerMetric) => { now: number; worst: number }
}

const percent = (v: number) => fmt(v, '%')
const bytes = (v: number) => fmt(v, 'B')
const plain = (v: number) => fmt(v, '')

function gauge(
  title: string,
  format: (v: number) => string,
  options: { limits?: Limits; percent?: boolean; used?: boolean; low?: boolean } = {},
): Gauge {
  const { limits, used, low } = options
  const series = (m: HealthServerMetric) =>
    used ? m.points.map((p) => ({ t: p.t, v: PERCENT - p.v })) : m.points
  const values = (m: HealthServerMetric) => series(m).map((p) => p.v)

  return {
    title,
    format,
    limits,
    percent: Boolean(options.percent),
    level: (v) =>
      !limits ? 'ok' : v >= limits.danger ? 'danger' : v >= limits.warn ? 'warn' : 'ok',
    series,
    read: (m) => ({
      now: used ? PERCENT - m.latest : m.latest,
      worst: low ? Math.min(...values(m)) : Math.max(...values(m)),
    }),
  }
}

export const SERVER_GAUGES: Record<keyof HealthServer['metrics'], Gauge> = {
  cpu: gauge('CPU', percent, { limits: CPU_LIMITS, percent: true }),
  memory: gauge('Memory used', percent, { limits: FILL_LIMITS, percent: true, used: true }),
  disk: gauge('Disk used', percent, { limits: FILL_LIMITS, percent: true }),
  load: gauge('Load per core', plain, { limits: LOAD_LIMITS }),
  heap: gauge('JVM heap', bytes),
}

export const DATABASE_GAUGES: Record<HealthDatabaseMetricKey, Gauge> = {
  cpu: gauge('CPU', percent, { limits: CPU_LIMITS, percent: true }),
  storage: gauge('Storage used', percent, { limits: FILL_LIMITS, percent: true }),
  sessions: gauge('Session limit', percent, { limits: SESSION_LIMITS, percent: true }),
  tablespace: gauge('Tablespace', percent, { limits: FILL_LIMITS, percent: true }),
  responseTime: gauge('Response time', duration),
  readLatency: gauge('Read latency', duration),
  writeLatency: gauge('Write latency', duration),
  activeSessions: gauge('Active sessions', plain),
  connections: gauge('Connections', count),
  memory: gauge('Free memory', bytes, { low: true }),
}

const RANK: Record<Level, number> = { ok: 0, warn: 1, danger: 2 }

export function worse(a: Level, b: Level): Level {
  return RANK[b] > RANK[a] ? b : a
}

type Breach = { level: Level; text: string }

function breaches<K extends string>(
  name: string,
  metrics: Partial<Record<K, HealthServerMetric>>,
  gauges: Record<K, Gauge>,
): Breach[] {
  const out: Breach[] = []
  for (const key of Object.keys(metrics) as K[]) {
    const gauge = gauges[key]
    const now = gauge.read(metrics[key]!).now
    const level = gauge.level(now)
    if (level !== 'ok')
      out.push({ level, text: `${name} ${gauge.title.toLowerCase()} ${gauge.format(now)}` })
  }

  return out
}

export function serverLevel(server: HealthServer): Level {
  return breaches(server.host, server.metrics, SERVER_GAUGES).reduce<Level>(
    (l, b) => worse(l, b.level),
    'ok',
  )
}

export function openFirst(incidents: HealthSections['incidents']): PagerDutyIncident[] {
  const openIds = new Set((incidents.open ?? []).map((i) => i.id))
  return [
    ...(incidents.open ?? []),
    ...(incidents.incidents ?? []).filter((i) => !openIds.has(i.id)),
  ]
}

export function latest(points: HealthPoint[]): number | null {
  const shown = points.filter((p) => p.v > 0)
  return shown.length ? shown[shown.length - 1].v : null
}

export function apmStoppedAt(requests: HealthPoint[], to: number, interval: number): number | null {
  const last = requests.filter((p) => p.v > 0).at(-1)
  if (!last || last.t >= to - STALE_INTERVALS * interval) return null
  return last.t
}

export function errorRate(traffic: HealthSections['traffic']): number | null {
  const requests = total(traffic.requests)
  if (requests < MIN_REQUESTS_FOR_RATE) return null
  return (total(traffic.errors) / requests) * PERCENT
}

export function latencyLevel(ms: number): Level {
  return ms >= SLOW_P95_MS ? 'danger' : ms >= SLUGGISH_P95_MS ? 'warn' : 'ok'
}

export function errorRateLevel(rate: number): Level {
  return rate >= ERROR_RATE_DANGER ? 'danger' : rate >= ERROR_RATE_WARN ? 'warn' : 'ok'
}

export type Check = { key: string; title: string; state: CheckState; text: string }

function fromSlot<K extends keyof HealthSections>(
  key: string,
  title: string,
  slot: Slot<K>,
  read: (value: HealthSections[K]) => { state: CheckState; text: string },
): Check {
  if (slot.state === 'loading') return { key, title, state: 'loading', text: 'Checking' }
  if (slot.state === 'unavailable') return { key, title, state: 'off', text: slot.reason }
  if (slot.state === 'error') return { key, title, state: 'off', text: 'Could not read it' }
  return { key, title, ...read(slot.value) }
}

function joined(parts: (string | false)[]): string {
  return parts.filter(Boolean).join(', ')
}

function incidentsCheck(slots: Slots): Check {
  return fromSlot('incidents', 'Incidents', slots.incidents, (v) => {
    if (Object.keys(v.errors).length) return { state: 'off', text: Object.values(v.errors)[0] }

    const open = v.open ?? []
    if (!open.length) return { state: 'ok', text: 'No open incidents' }

    const triggered = open.filter((i) => i.status === 'triggered').length
    const acknowledged = open.length - triggered

    return {
      state: triggered ? 'danger' : 'warn',
      text: joined([
        triggered > 0 && `${triggered} triggered`,
        acknowledged > 0 && `${acknowledged} acknowledged`,
      ]),
    }
  })
}

function monitorsCheck(slots: Slots): Check {
  return fromSlot('monitors', 'Monitors', slots.monitors, (v) => {
    if (!v.monitors.length) return { state: 'off', text: 'No monitors watch it' }

    const alerting = v.monitors.filter((m) => m.state === 'Alert').length
    const warning = v.monitors.filter((m) => m.state === 'Warn').length
    const noData = v.monitors.filter((m) => m.state === 'No Data').length
    if (!alerting && !warning)
      return {
        state: 'ok',
        text: noData
          ? `${noData} of ${v.monitors.length} without data`
          : `All ${v.monitors.length} OK`,
      }

    return {
      state: alerting ? 'danger' : 'warn',
      text: joined([alerting > 0 && `${alerting} alerting`, warning > 0 && `${warning} warning`]),
    }
  })
}

function apmCheck(slots: Slots, meta: HealthMeta): Check {
  return fromSlot('apm', 'Requests', slots.traffic, (v) => {
    const p95 = latest(v.p95Ms)
    if (!total(v.requests) || p95 === null) return { state: 'off', text: 'No APM data' }

    const stoppedAt = apmStoppedAt(v.requests, meta.to, meta.interval)
    if (stoppedAt !== null) return { state: 'warn', text: `No data since ${whenOf(stoppedAt)}` }

    const rate = errorRate(v)
    const level = worse(latencyLevel(p95), rate === null ? 'ok' : errorRateLevel(rate))

    return {
      state: level,
      text: joined([`p95 ${duration(p95)}`, rate !== null && `${fmt(rate, '%')} errors`]),
    }
  })
}

function serversCheck(slots: Slots): Check {
  return fromSlot('servers', 'Servers', slots.servers, (v) => {
    if (!v.servers.length) return { state: 'off', text: 'No metrics' }

    const found = v.servers.flatMap((s) => breaches(shortHost(s.host), s.metrics, SERVER_GAUGES))
    if (!found.length)
      return { state: 'ok', text: `${plural(v.servers.length, 'server')} within limits` }

    const level = found.reduce<Level>((l, b) => worse(l, b.level), 'ok')
    const shown = found.filter((b) => b.level === level)

    return {
      state: level,
      text: shown.length > 1 ? `${shown[0].text} and ${shown.length - 1} more` : shown[0].text,
    }
  })
}

function databaseCheck(slots: Slots): Check {
  return fromSlot('database', 'Database', slots.database, (v) => {
    if (!v.databases.length) return { state: 'off', text: 'No metrics' }
    const found = v.databases.flatMap((d) => breaches(d.id, d.metrics, DATABASE_GAUGES))
    if (!found.length) return { state: 'ok', text: 'Within limits' }
    const level = found.reduce<Level>((l, b) => worse(l, b.level), 'ok')
    return { state: level, text: found.filter((b) => b.level === level)[0].text }
  })
}

export function pagerDutyChecks(slots: Slots): Check[] {
  return [incidentsCheck(slots)]
}

export function datadogChecks(slots: Slots, matched: boolean, meta: HealthMeta): Check[] {
  if (!matched) return [monitorsCheck(slots)]
  return [monitorsCheck(slots), apmCheck(slots, meta), serversCheck(slots), databaseCheck(slots)]
}

export function verdictOf(checks: Check[]): CheckState {
  if (checks.some((c) => c.state === 'danger')) return 'danger'
  if (checks.some((c) => c.state === 'warn')) return 'warn'
  if (checks.some((c) => c.state === 'loading')) return 'loading'
  return checks.some((c) => c.state === 'ok') ? 'ok' : 'off'
}
