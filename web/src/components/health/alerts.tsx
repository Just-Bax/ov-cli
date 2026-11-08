import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  CaretRight as ChevronRightIcon,
  Sparkle as SparklesIcon,
} from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { HealthMonitor, PagerDutyIncident, PagerDutyIncidentDetail } from '@shared/types.ts'
import { Card, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { RANGE_WORDS, ready, span, utcMs, whenOf } from './data'
import { maintenanceCheck } from './maintenance'
import {
  type Check,
  type CheckState,
  datadogChecks,
  openFirst,
  pagerDutyChecks,
  verdictOf,
} from './signals'
import {
  ask,
  Body,
  type Context,
  Quiet,
  RowsSkeleton,
  ShowAll,
  SourceTag,
  STATE_DOT,
  Stat,
  Tile,
  tileId,
  type Vendor,
} from './tiles'

const INCIDENT_ROWS = 5
const MONITOR_ROWS = 6
const MONITOR_ROW_PX = 28
const DETAIL_TIMELINE_ROWS = 6

const VERDICTS: Record<CheckState, string> = {
  danger: 'Needs attention',
  warn: 'Worth a look',
  ok: 'All clear',
  loading: 'Checking',
  off: 'Nothing to go on',
}

const CHECK_TILES: Record<string, string> = { apm: 'traffic' }

const INCIDENT_DOT: Record<string, string> = {
  triggered: 'bg-danger',
  acknowledged: 'bg-warn',
  resolved: 'bg-ok',
}

const MONITOR_STATES = [
  { state: 'Alert', label: 'Alert', fill: 'bg-danger' },
  { state: 'Warn', label: 'Warn', fill: 'bg-warn' },
  { state: 'No Data', label: 'No data', fill: 'bg-line-strong' },
  { state: 'OK', label: 'OK', fill: 'bg-ok' },
] as const

const STATE_TEXT: Record<CheckState, string> = {
  danger: 'text-danger',
  warn: 'text-warn',
  ok: 'text-fg',
  off: 'text-muted',
  loading: 'text-muted',
}

function jumpTo(key: string) {
  document
    .getElementById(tileId(CHECK_TILES[key] ?? key))
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function CheckCell({ check }: { check: Check }) {
  return (
    <button
      type="button"
      onClick={() => jumpTo(check.key)}
      className="bg-raised hover:bg-line min-w-0 rounded-2xl px-3.5 py-2.5 text-left"
    >
      <div className="text-muted flex items-center gap-1.5 text-[11.5px]">
        <span className={cn('size-1.5 shrink-0 rounded-full', STATE_DOT[check.state])} />
        {check.title}
      </div>
      {check.state === 'loading' ? (
        <Skeleton className="mt-1.5 h-4 w-24" />
      ) : (
        <div
          title={check.text}
          className={cn('mt-0.5 truncate text-[13px] font-medium', STATE_TEXT[check.state])}
        >
          {check.text}
        </div>
      )}
    </button>
  )
}

function CheckGroup({ vendor, checks }: { vendor: Vendor; checks: Check[] }) {
  return (
    <div className="min-w-0">
      <div className="pb-2">
        <SourceTag vendor={vendor} />
      </div>
      <div
        className={cn(
          'grid gap-2',
          checks.length > 1 ? 'grid-cols-2 md:grid-cols-4' : 'grid-cols-1',
        )}
      >
        {checks.map((c) => (
          <CheckCell key={c.key} check={c} />
        ))}
      </div>
    </div>
  )
}

export function Overview({ ctx, matched }: { ctx: Context; matched: boolean }) {
  const pagerduty = pagerDutyChecks(ctx.slots)
  const datadog = datadogChecks(ctx.slots, matched, ctx.meta)
  const oneteam = [maintenanceCheck(ctx.slots)]
  const state = verdictOf([...pagerduty, ...datadog, ...oneteam])

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="flex items-center gap-2">
          <span className={cn('size-2.5 shrink-0 rounded-full', STATE_DOT[state])} />
          <span className={cn('text-[15px] font-semibold', STATE_TEXT[state])}>
            {VERDICTS[state]}
          </span>
        </span>
        <span className="text-muted text-[12.5px]">
          {ctx.label}, last {RANGE_WORDS[ctx.range]}. Click a check to see its details.
        </span>
      </div>
      <div className="mt-3.5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,4fr)_minmax(0,1fr)]">
        <CheckGroup vendor="pagerduty" checks={pagerduty} />
        <CheckGroup vendor="datadog" checks={datadog} />
        <CheckGroup vendor="oneteam" checks={oneteam} />
      </div>
    </Card>
  )
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
                {whenOf(utcMs(e.time))}
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

function IncidentRow({
  incident: i,
  open,
  onToggle,
  ctx,
}: {
  incident: PagerDutyIncident
  open: boolean
  onToggle: () => void
  ctx: Context
}) {
  const age =
    i.status === 'resolved'
      ? `resolved in ${span(utcMs(i.created), utcMs(i.changed))}`
      : `open ${span(utcMs(i.created), Date.now())}`

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="hover:bg-raised flex w-full items-center gap-2.5 rounded-full px-3 py-1.5 text-left"
      >
        <span className={cn('size-2 shrink-0 rounded-full', INCIDENT_DOT[i.status])} />
        <span className="min-w-0 flex-1">
          <span className="text-fg block truncate text-[12.5px]">{i.title}</span>
          <span className="text-faint block truncate text-[11px]">
            #{i.number}
            {i.service ? ` in ${i.service}` : ''}, {age}
          </span>
        </span>
        {i.urgency === 'high' ? (
          <span className="bg-danger-soft text-danger shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium">
            high
          </span>
        ) : null}
        <ChevronRightIcon
          className={cn('text-faint size-3.5 shrink-0 transition-transform', open && 'rotate-90')}
        />
      </button>
      {open ? <IncidentDetail incident={i} ctx={ctx} /> : null}
    </div>
  )
}

export function IncidentsTile({ ctx, className }: { ctx: Context; className?: string }) {
  const [open, setOpen] = useState<string>()
  const [all, setAll] = useState(false)
  const data = ready(ctx.slots.incidents)
  const oncall = data?.oncall?.map((o) => o.user).join(', ')

  return (
    <Tile
      id={tileId('incidents')}
      vendor="pagerduty"
      title="Incidents"
      aside={oncall ? `On call: ${oncall}` : undefined}
      link={data?.webUrl ? `${data.webUrl}/incidents` : undefined}
      onAsk={() =>
        ask(
          ctx,
          'Review the open and recent PagerDuty incidents for this instance and what caused them.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.incidents}>
        {(v) => {
          if (Object.keys(v.errors).length)
            return <div className="text-danger text-[12.5px]">{Object.values(v.errors)[0]}</div>

          const openNow = v.open ?? []
          const triggered = openNow.filter((i) => i.status === 'triggered').length
          const resolved = (v.incidents ?? []).filter((i) => i.status === 'resolved').length
          const rows = openFirst(v)

          return (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Triggered" value={triggered} level={triggered ? 'danger' : 'ok'} />
                <Stat
                  label="Acknowledged"
                  value={openNow.length - triggered}
                  level={openNow.length - triggered ? 'warn' : 'ok'}
                />
                <Stat
                  label="Resolved"
                  value={resolved}
                  hint={`Resolved in the last ${RANGE_WORDS[ctx.range]}`}
                />
              </div>
              {rows.length ? (
                <div className="-mx-2">
                  {(all ? rows : rows.slice(0, INCIDENT_ROWS)).map((i) => (
                    <IncidentRow
                      key={i.id}
                      incident={i}
                      ctx={ctx}
                      open={open === i.id}
                      onToggle={() => setOpen(open === i.id ? undefined : i.id)}
                    />
                  ))}
                  <ShowAll
                    shown={INCIDENT_ROWS}
                    total={rows.length}
                    open={all}
                    onToggle={() => setAll(!all)}
                  />
                </div>
              ) : (
                <Quiet>No incidents in the last {RANGE_WORDS[ctx.range]}.</Quiet>
              )}
            </div>
          )
        }}
      </Body>
    </Tile>
  )
}

const TEMPLATE = /\{\{\s*([\w-]+)(?:\.[\w-]+)*\s*\}\}/g
const TRAILING_WORDS = /(?:\s+(?:on|for|host|device|in|of)|\s*[-/:\u2014])+\s*$/i
const WATCHING_WORDS: Record<string, [string, string]> = {
  host: ['server', 'servers'],
  dbinstanceidentifier: ['database', 'databases'],
  server: ['database', 'databases'],
  site: ['site', 'sites'],
}

function monitorName(m: HealthMonitor): string {
  const group = m.groups[0]
  if (!group)
    return m.name
      .replace(TEMPLATE, '')
      .replace(/\s{2,}/g, ' ')
      .replace(TRAILING_WORDS, '')

  const values = new Map(
    group.split(',').map((part) => {
      const [tag, ...rest] = part.split(':')
      return [tag, rest.join(':').split('.')[0]] as const
    }),
  )

  return m.name.replace(TEMPLATE, (_, tag: string) => values.get(tag) || tag)
}

function watchingLabel(m: HealthMonitor): string {
  if (m.groups.length)
    return m.groups.map((g) => g.split(',')[0].split(':').pop()?.split('.')[0]).join(', ')
  if (!m.watching) return ''
  const [n, tag] = m.watching
  const words = WATCHING_WORDS[tag]
  return words ? `${n} ${n === 1 ? words[0] : words[1]}` : ''
}

function StateBar({ monitors }: { monitors: HealthMonitor[] }) {
  const counts = MONITOR_STATES.map((s) => ({
    ...s,
    n: monitors.filter((m) => m.state === s.state).length,
  }))

  return (
    <div>
      <div className="bg-line flex h-2 gap-0.5 overflow-hidden rounded-full">
        {counts
          .filter((c) => c.n)
          .map((c) => (
            <div key={c.state} className={c.fill} style={{ flexGrow: c.n }} />
          ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]">
        {counts.map((c) => (
          <span key={c.state} className="text-muted inline-flex items-center gap-1.5">
            <span className={cn('size-2 rounded-full', c.fill)} />
            {c.label}
            <span className="text-fg font-semibold tabular-nums">{c.n}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function MonitorRow({ m, appUrl }: { m: HealthMonitor; appUrl: string }) {
  const fill = MONITOR_STATES.find((s) => s.state === m.state)?.fill ?? 'bg-line-strong'

  return (
    <a
      href={`${appUrl}/monitors/${m.id}`}
      target="_blank"
      rel="noreferrer"
      title={m.name}
      className="hover:bg-raised flex shrink-0 items-center gap-2.5 rounded-full px-3"
      style={{ height: MONITOR_ROW_PX }}
    >
      <span className={cn('size-2 shrink-0 rounded-full', fill)} />
      <span
        className={cn(
          'min-w-0 flex-1 truncate text-[12.5px]',
          m.state === 'OK' ? 'text-text' : 'text-fg font-medium',
        )}
      >
        {monitorName(m)}
      </span>
      <span className="text-faint max-w-[35%] shrink-0 truncate text-[11px]">
        {watchingLabel(m)}
      </span>
    </a>
  )
}

function useRowsThatFit(area: HTMLElement | null): number {
  const [fit, setFit] = useState(0)

  useEffect(() => {
    if (!area) return
    const measure = () => setFit(Math.floor(area.clientHeight / MONITOR_ROW_PX))
    const observer = new ResizeObserver(measure)
    observer.observe(area)
    return () => observer.disconnect()
  }, [area])

  return fit
}

export function MonitorsTile({ ctx, className }: { ctx: Context; className?: string }) {
  const [all, setAll] = useState(false)
  const [area, setArea] = useState<HTMLDivElement | null>(null)
  const fit = useRowsThatFit(area)

  return (
    <Tile
      id={tileId('monitors')}
      vendor="datadog"
      area="Monitors"
      title="Alerts"
      aside="Monitors that watch this instance"
      link={ctx.meta.links.monitors}
      onAsk={() =>
        ask(
          ctx,
          'Review the Datadog monitors on this instance that are alerting, warning or without data: what each one watches, since when, and the likely cause.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.monitors}>
        {(v) => {
          if (!v.monitors.length)
            return <Quiet muted>No Datadog monitor watches these servers or this database.</Quiet>

          const firing = v.monitors.filter((m) => m.state !== 'OK')
          const quiet = v.monitors.filter((m) => m.state === 'OK')
          const least = Math.max(0, MONITOR_ROWS - firing.length)
          const shown = all ? quiet : quiet.slice(0, Math.max(least, fit))

          return (
            <div className="flex flex-1 flex-col gap-3">
              <StateBar monitors={v.monitors} />
              <div className="-mx-2 flex flex-1 flex-col">
                {firing.map((m) => (
                  <MonitorRow key={m.id} m={m} appUrl={ctx.meta.appUrl} />
                ))}
                <div
                  ref={setArea}
                  className={cn('flex flex-col', all ? null : 'flex-1 basis-0 overflow-hidden')}
                  style={{ minHeight: Math.min(least, quiet.length) * MONITOR_ROW_PX }}
                >
                  {shown.map((m) => (
                    <MonitorRow key={m.id} m={m} appUrl={ctx.meta.appUrl} />
                  ))}
                </div>
                <ShowAll
                  shown={firing.length + shown.length}
                  total={v.monitors.length}
                  open={all}
                  onToggle={() => setAll(!all)}
                />
              </div>
            </div>
          )
        }}
      </Body>
    </Tile>
  )
}
