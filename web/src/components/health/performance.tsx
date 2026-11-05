import { Warning as ExclamationTriangleIcon } from '@phosphor-icons/react'
import type { HealthPoint, MaintenanceItem } from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { Skeleton } from '@/components/common/ui'
import { DATADOG_PURPLE } from '@/components/integrations/Datadog'
import { HOUR_MS } from '@/lib/time'
import { type EventLane, Lanes } from './charts'
import { count, duration, fmt, ready, total, utcMs } from './data'
import { maintenanceLabel, whenOf } from './maintenance'
import {
  apmStoppedAt,
  errorRate,
  errorRateLevel,
  latencyLevel,
  SLOW_P95_MS,
  SLUGGISH_P95_MS,
} from './signals'
import { ask, Bar, Body, type Context, Quiet, Stat, Tile } from './tiles'

const BLUE = '#42a5f5'
const RED = '#e53935'
const INCIDENT_COLOR = '#e46b00'
const MAINTENANCE_COLOR = '#78909c'
const ENDPOINT_ROWS = 8
const CAUSE_WINDOW_MS = 2 * HOUR_MS
const REQUESTS_HEIGHT = 64
const LATENCY_HEIGHT = 64
const ERRORS_HEIGHT = 36

function lastPoint(points: HealthPoint[]): HealthPoint | undefined {
  return points.filter((p) => p.v > 0).at(-1)
}

function likelyCause(items: MaintenanceItem[], stoppedAt: number): MaintenanceItem | undefined {
  return items.find(
    (i) =>
      i.start !== null &&
      i.start <= stoppedAt + CAUSE_WINDOW_MS &&
      i.start >= stoppedAt - CAUSE_WINDOW_MS,
  )
}

function eventLanes(ctx: Context): EventLane[] {
  const incidents = ready(ctx.slots.incidents)
  const maintenance = ready(ctx.slots.maintenance)?.items ?? []
  const seen = new Set<string>()
  const all = [...(incidents?.open ?? []), ...(incidents?.incidents ?? [])].filter((i) => {
    if (seen.has(i.id)) return false
    seen.add(i.id)
    return true
  })

  return [
    {
      label: 'Maintenance',
      items: maintenance
        .filter((m) => m.start !== null)
        .map((m) => ({
          from: m.start!,
          to: m.end ?? undefined,
          color: MAINTENANCE_COLOR,
          label: `OneTeam ${maintenanceLabel(m)}, ${m.status.toLowerCase()}`,
        })),
    },
    {
      label: 'Incidents',
      items: all.map((i) => ({
        from: utcMs(i.created),
        to: i.status === 'resolved' ? utcMs(i.changed) : undefined,
        color: INCIDENT_COLOR,
        label: `PagerDuty #${i.number}: ${i.title}`,
      })),
    },
  ]
}

function StaleNote({ ctx, stoppedAt }: { ctx: Context; stoppedAt: number }) {
  const cause = likelyCause(ready(ctx.slots.maintenance)?.items ?? [], stoppedAt)

  return (
    <div className="bg-warn-soft text-text flex items-start gap-2 rounded-2xl px-3.5 py-2.5 text-[12px]">
      <ExclamationTriangleIcon className="text-warn mt-0.5 size-3.5 shrink-0" />
      <span>
        No APM data since {whenOf(stoppedAt)}.
        {cause
          ? ` That is right after OneTeam ${maintenanceLabel(cause)} (${cause.key}), so the tracer may not have come back after it.`
          : ' The tracer on these servers may have stopped.'}
      </span>
    </div>
  )
}

export function PerformanceTile({ ctx, className }: { ctx: Context; className?: string }) {
  const { meta, slots } = ctx
  const showSkeleton = useSkeleton(slots.traffic.state === 'loading')

  return (
    <Tile
      vendor="datadog"
      area="APM"
      title="Requests and latency"
      aside="Web requests to these servers"
      link={meta.links.apm}
      onAsk={() =>
        ask(
          ctx,
          'Walk the request timeline of this instance: requests, p95 latency and errors from APM, lined up with PagerDuty incidents and OneTeam maintenance such as deployments and restarts. Find what changed together, when, and the most likely cause. If APM data stops, say when and why it likely stopped.',
        )
      }
      className={className}
    >
      {showSkeleton ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-[58px] rounded-2xl" />
            ))}
          </div>
          <Skeleton className="h-[230px] w-full rounded-2xl" />
        </div>
      ) : (
        <Body slot={slots.traffic}>
          {(v) => {
            const requests = total(v.requests)
            if (!requests)
              return (
                <Quiet muted>
                  No APM data from these servers in this window. Requests and latency need the
                  Datadog APM tracer on the web servers.
                </Quiet>
              )

            const stoppedAt = apmStoppedAt(v.requests, meta.to, meta.interval)
            const now = stoppedAt === null ? lastPoint(v.p95Ms)?.v : undefined
            const worst = Math.max(0, ...v.p95Ms.map((p) => p.v))
            const rate = errorRate(v)

            return (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  <Stat label="Requests" value={count(requests)} />
                  <Stat
                    label="Error rate"
                    value={rate === null ? '-' : fmt(rate, '%')}
                    level={rate === null ? 'ok' : errorRateLevel(rate)}
                    hint={`${count(total(v.errors))} failed requests`}
                  />
                  <Stat
                    label="p95 now"
                    value={now ? duration(now) : '-'}
                    level={now ? latencyLevel(now) : 'ok'}
                    hint={`Slow from ${duration(SLUGGISH_P95_MS)}, very slow from ${duration(SLOW_P95_MS)}`}
                  />
                  <Stat
                    label="p95 worst"
                    value={worst ? duration(worst) : '-'}
                    level={latencyLevel(worst)}
                  />
                </div>
                {stoppedAt === null ? null : <StaleNote ctx={ctx} stoppedAt={stoppedAt} />}
                <Lanes
                  from={meta.from}
                  to={meta.to}
                  interval={meta.interval}
                  range={ctx.range}
                  lanes={[
                    {
                      label: 'Requests',
                      color: BLUE,
                      kind: 'bars',
                      points: v.requests,
                      format: count,
                      height: REQUESTS_HEIGHT,
                    },
                    {
                      label: 'p95',
                      color: DATADOG_PURPLE,
                      kind: 'line',
                      points: v.p95Ms,
                      format: duration,
                      height: LATENCY_HEIGHT,
                      limit: SLUGGISH_P95_MS,
                    },
                    {
                      label: 'Errors',
                      color: RED,
                      kind: 'bars',
                      points: v.errors,
                      format: count,
                      height: ERRORS_HEIGHT,
                    },
                  ]}
                  events={eventLanes(ctx)}
                />
              </div>
            )
          }}
        </Body>
      )}
    </Tile>
  )
}

export function EndpointsTile({ ctx, className }: { ctx: Context; className?: string }) {
  return (
    <Tile
      vendor="datadog"
      area="APM"
      title="Slowest endpoints"
      aside="p95 over the window"
      link={ctx.meta.links.apm}
      onAsk={() =>
        ask(
          ctx,
          'Why are the slowest endpoints of this instance slow? Use APM traces and the instance configuration.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.traffic}>
        {(v) => {
          if (!v.slowEndpoints.length)
            return <Quiet muted>No traced requests in this window.</Quiet>

          const max = Math.max(...v.slowEndpoints.map((s) => s.p95Ms))

          return (
            <div className="space-y-3">
              {v.slowEndpoints.slice(0, ENDPOINT_ROWS).map((s) => {
                const level = latencyLevel(s.p95Ms)

                return (
                  <div key={s.resource} title={`${s.resource}\n${count(s.count)} traced calls`}>
                    <div className="flex items-baseline gap-3">
                      <span className="text-fg min-w-0 flex-1 truncate font-mono text-[11.5px]">
                        {s.resource}
                      </span>
                      <span className="text-fg w-12 shrink-0 text-right text-[12px] font-semibold tabular-nums">
                        {duration(s.p95Ms)}
                      </span>
                    </div>
                    <Bar
                      value={s.p95Ms}
                      max={max}
                      fill={
                        level === 'danger' ? 'bg-danger' : level === 'warn' ? 'bg-warn' : 'bg-brand'
                      }
                    />
                  </div>
                )
              })}
            </div>
          )
        }}
      </Body>
    </Tile>
  )
}
