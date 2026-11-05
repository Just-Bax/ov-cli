import type { HealthServerMetric } from '@shared/types.ts'
import { cn } from '@/lib/cn'
import { shortHost } from '@/lib/servers'
import { MetricChart } from './charts'
import {
  DATABASE_GAUGES,
  type Gauge,
  type Level,
  SERVER_GAUGES,
  serverLevel,
  worse,
} from './signals'
import {
  ask,
  Body,
  type Context,
  LEVEL_TEXT,
  Quiet,
  RowsSkeleton,
  STATE_DOT,
  Tile,
  tileId,
} from './tiles'

const PERCENT_CEILING = 100
const SERVER_COLUMN = '120px'

const LEVEL_COLOR: Record<Level, string> = {
  ok: '#42a5f5',
  warn: '#e46b00',
  danger: '#ce2605',
}

function MetricCell({
  gauge,
  metric,
  label,
}: {
  gauge: Gauge
  metric?: HealthServerMetric
  label?: string
}) {
  if (!metric)
    return (
      <div className="min-w-0">
        {label ? <div className="text-muted text-[11.5px]">{label}</div> : null}
        <div className="text-faint text-[12px]">No data</div>
      </div>
    )

  const { now, worst } = gauge.read(metric)
  const level = gauge.level(now)
  const worstLevel = gauge.level(worst)

  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-2">
        {label ? <span className="text-muted truncate text-[11.5px]">{label}</span> : null}
        <span className={cn('text-[14px] font-semibold tabular-nums', LEVEL_TEXT[level])}>
          {gauge.format(now)}
        </span>
        <span
          className={cn(
            'ml-auto shrink-0 text-[11px] tabular-nums',
            worstLevel === 'ok' ? 'text-faint' : LEVEL_TEXT[worstLevel],
          )}
          title="Worst point in this window"
        >
          worst {gauge.format(worst)}
        </span>
      </div>
      <div className="mt-1.5">
        <MetricChart
          points={gauge.series(metric)}
          color={LEVEL_COLOR[worse(level, worstLevel)]}
          limit={gauge.limits?.warn}
          ceiling={gauge.percent ? PERCENT_CEILING : undefined}
          format={gauge.format}
        />
      </div>
    </div>
  )
}

function limitHint(gauge: Gauge): string | undefined {
  return gauge.limits ? `limit ${gauge.format(gauge.limits.warn)}` : undefined
}

export function ServersTile({ ctx, className }: { ctx: Context; className?: string }) {
  return (
    <Tile
      id={tileId('servers')}
      vendor="datadog"
      area="Infrastructure"
      title="Servers"
      aside="Now and the worst point in this window. The dashed line is the limit."
      link={ctx.meta.links.metrics}
      onAsk={() =>
        ask(
          ctx,
          'Compare the servers of this instance: CPU, memory, disk, load and JVM heap. Say which one stands out and why.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.servers} skeleton={<RowsSkeleton rows={4} />}>
        {(v) => {
          if (!v.servers.length) return <Quiet muted>No server metrics in this window.</Quiet>

          const keys = (Object.keys(SERVER_GAUGES) as (keyof typeof SERVER_GAUGES)[]).filter((k) =>
            v.servers.some((s) => s.metrics[k]),
          )
          const columns = `${SERVER_COLUMN} repeat(${keys.length}, minmax(0, 1fr))`

          return (
            <div>
              <div className="grid w-full gap-x-6" style={{ gridTemplateColumns: columns }}>
                <div className="text-faint pb-2 text-[11px] font-medium">Server</div>
                {keys.map((k) => (
                  <div key={k} className="text-faint pb-2 text-[11px] font-medium">
                    {SERVER_GAUGES[k].title}
                    {limitHint(SERVER_GAUGES[k]) ? (
                      <span className="font-normal">, {limitHint(SERVER_GAUGES[k])}</span>
                    ) : null}
                  </div>
                ))}
                {v.servers.map((s) => (
                  <div key={s.host} className="contents">
                    <div
                      className="border-line flex min-w-0 items-start gap-2 border-t py-3"
                      title={s.host}
                    >
                      <span
                        className={cn(
                          'mt-1.5 size-2 shrink-0 rounded-full',
                          STATE_DOT[serverLevel(s)],
                        )}
                      />
                      <span className="min-w-0">
                        <span className="text-fg block truncate text-[13px] font-medium">
                          {shortHost(s.host)}
                        </span>
                        <span className="text-muted text-[11px]">{s.role}</span>
                      </span>
                    </div>
                    {keys.map((k) => (
                      <div key={k} className="border-line border-t py-3">
                        <MetricCell gauge={SERVER_GAUGES[k]} metric={s.metrics[k]} />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )
        }}
      </Body>
    </Tile>
  )
}

export function DatabaseTile({ ctx, className }: { ctx: Context; className?: string }) {
  return (
    <Tile
      id={tileId('database')}
      vendor="datadog"
      area="Database"
      title="Database"
      aside="Now and the worst point in this window"
      onAsk={() =>
        ask(
          ctx,
          'Check the database of this instance: CPU, free memory, storage, connections, read and write latency, active sessions and response time, Oracle session limit and tablespace use, and any database monitors or incidents. If the database is shared with other instances, say how much of the load is likely this one. Say what stands out and why.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.database} skeleton={<RowsSkeleton rows={4} />}>
        {(v) => {
          if (!v.databases.length) return <Quiet muted>No database metrics in this window.</Quiet>

          return (
            <div className="space-y-5">
              {v.databases.map((d) => {
                const keys = (
                  Object.keys(DATABASE_GAUGES) as (keyof typeof DATABASE_GAUGES)[]
                ).filter((k) => d.metrics[k])

                return (
                  <div key={d.id} className="min-w-0">
                    <div
                      className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1"
                      title={d.endpoint || d.id}
                    >
                      <span className="text-fg truncate text-[13px] font-medium">{d.id}</span>
                      {d.engine ? (
                        <span className="text-brand-strong bg-brand-soft rounded-full px-1.5 py-px text-[10.5px] font-medium">
                          {d.engine}
                        </span>
                      ) : null}
                      {d.shared ? (
                        <span
                          title="Other instances use this database too, so its load is not only this instance's"
                          className="bg-raised text-muted rounded-full px-1.5 py-px text-[10.5px] font-medium"
                        >
                          shared
                        </span>
                      ) : null}
                    </div>
                    {keys.length ? (
                      <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-4">
                        {keys.map((k) => (
                          <MetricCell
                            key={k}
                            gauge={DATABASE_GAUGES[k]}
                            metric={d.metrics[k]}
                            label={DATABASE_GAUGES[k].title}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="text-faint text-[12px]">No metrics from this database</div>
                    )}
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
