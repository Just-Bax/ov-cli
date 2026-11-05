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
import { count, duration, fmt, type Slot, type Slots, total } from './data'

export type Level = 'danger' | 'warn' | 'ok'
export type CheckState = Level | 'off' | 'loading'

export const SLOW_P95_MS = 10_000
export const SLUGGISH_P95_MS = 3000
const ERROR_RATE_WARN = 1
const ERROR_RATE_DANGER = 5
const MIN_REQUESTS_FOR_RATE = 100
const PERCENT = 100
const STALE_INTERVALS = 3

function shortWhen(ms: number): string {
  return new Date(ms).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

type Limits = { warn: number; danger: number }

const atLeast =
  (limits: Limits) =>
  (v: number): Level =>
    v >= limits.danger ? 'danger' : v >= limits.warn ? 'warn' : 'ok'

const calm = (): Level => 'ok'

export type Gauge = {
  title: string
  format: (v: number) => string
  level: (v: number) => Level
  read: (m: HealthServerMetric) => { now: number; worst: number }
  meter: boolean
}

const percent = (v: number) => fmt(v, '%')
const bytes = (v: number) => fmt(v, 'B')
const plain = (v: number) => fmt(v, '')
const lowest = (points: HealthPoint[]) => Math.min(...points.map((p) => p.v))
const highest = (m: HealthServerMetric) => ({ now: m.latest, worst: m.max })
const lowestFirst = (m: HealthServerMetric) => ({ now: m.latest, worst: lowest(m.points) })
const usedFromFree = (m: HealthServerMetric) => ({
  now: PERCENT - m.latest,
  worst: PERCENT - lowest(m.points),
})

export const SERVER_GAUGES: Record<keyof HealthServer['metrics'], Gauge> = {
  cpu: {
    title: 'CPU',
    format: percent,
    level: atLeast({ warn: 65, danger: 85 }),
    read: highest,
    meter: true,
  },
  memory: {
    title: 'Memory',
    format: percent,
    level: atLeast({ warn: 80, danger: 90 }),
    read: usedFromFree,
    meter: true,
  },
  disk: {
    title: 'Disk',
    format: percent,
    level: atLeast({ warn: 80, danger: 90 }),
    read: highest,
    meter: true,
  },
  load: {
    title: 'Load per core',
    format: plain,
    level: atLeast({ warn: 1, danger: 1.5 }),
    read: highest,
    meter: false,
  },
  heap: { title: 'JVM heap', format: bytes, level: calm, read: highest, meter: false },
}

export const DATABASE_GAUGES: Record<HealthDatabaseMetricKey, Gauge> = {
  cpu: {
    title: 'CPU',
    format: percent,
    level: atLeast({ warn: 65, danger: 85 }),
    read: highest,
    meter: true,
  },
  storage: {
    title: 'Storage',
    format: percent,
    level: atLeast({ warn: 80, danger: 90 }),
    read: highest,
    meter: true,
  },
  sessions: {
    title: 'Session limit',
    format: percent,
    level: atLeast({ warn: 70, danger: 90 }),
    read: highest,
    meter: true,
  },
  tablespace: {
    title: 'Tablespace',
    format: percent,
    level: atLeast({ warn: 80, danger: 90 }),
    read: highest,
    meter: true,
  },
  readLatency: {
    title: 'Read latency',
    format: duration,
    level: calm,
    read: highest,
    meter: false,
  },
  writeLatency: {
    title: 'Write latency',
    format: duration,
    level: calm,
    read: highest,
    meter: false,
  },
  responseTime: {
    title: 'Response time',
    format: duration,
    level: calm,
    read: highest,
    meter: false,
  },
  connections: { title: 'Connections', format: count, level: calm, read: highest, meter: false },
  activeSessions: {
    title: 'Active sessions',
    format: plain,
    level: calm,
    read: highest,
    meter: false,
  },
  memory: { title: 'Free memory', format: bytes, level: calm, read: lowestFirst, meter: false },
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

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function joined(parts: (string | false)[]): string {
  return parts.filter(Boolean).join(', ')
}

function incidentsCheck(slots: Slots): Check {
  return fromSlot('incidents', 'Incidents', slots.incidents, (v) => {
    if (Object.keys(v.errors).length) return { state: 'off', text: Object.values(v.errors)[0] }

    const open = v.open ?? []
    const triggered = open.filter((i) => i.status === 'triggered').length
    const acknowledged = open.length - triggered
    if (!open.length) return { state: 'ok', text: 'No open incidents' }

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
    const alerting = v.monitors.filter((m) => m.state === 'Alert').length
    const warning = v.monitors.filter((m) => m.state === 'Warn').length
    const noData = v.monitors.filter((m) => m.state === 'No Data').length
    if (!v.monitors.length) return { state: 'off', text: 'No monitors watch it' }
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
    if (stoppedAt !== null) return { state: 'warn', text: `No data since ${shortWhen(stoppedAt)}` }

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
