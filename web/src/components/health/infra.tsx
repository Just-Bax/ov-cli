import type { HealthServerMetric } from '@shared/types.ts'
import { cn } from '@/lib/cn'
import { shortHost } from '@/lib/servers'
import { DATABASE_GAUGES, type Gauge, SERVER_GAUGES, serverLevel } from './signals'
import {
  ask,
  Body,
  type Context,
  Meter,
  Quiet,
  Reading,
  RowsSkeleton,
  STATE_DOT,
  Tile,
} from './tiles'

function gaugesOf<K extends string>(
  metrics: Partial<Record<K, HealthServerMetric>>,
  gauges: Record<K, Gauge>,
) {
  return (Object.keys(gauges) as K[])
    .filter((k) => metrics[k])
    .map((k) => {
      const gauge = gauges[k]
      const { now, worst } = gauge.read(metrics[k]!)
      return { key: k, gauge, now, worst, level: gauge.level(now), worstLevel: gauge.level(worst) }
    })
}

function Readings<K extends string>({
  metrics,
  gauges,
}: {
  metrics: Partial<Record<K, HealthServerMetric>>
  gauges: Record<K, Gauge>
}) {
  const shown = gaugesOf(metrics, gauges)

  return (
    <>
      <div className="space-y-2.5">
        {shown
          .filter((g) => g.gauge.meter)
          .map((g) => (
            <Meter
              key={g.key}
              label={g.gauge.title}
              now={g.now}
              worst={g.worst}
              level={g.level}
              worstLevel={g.worstLevel}
              format={g.gauge.format}
            />
          ))}
      </div>
      {shown.some((g) => !g.gauge.meter) ? (
        <div className="border-line mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t pt-2.5">
          {shown
            .filter((g) => !g.gauge.meter)
            .map((g) => (
              <Reading
                key={g.key}
                label={g.gauge.title}
                value={g.gauge.format(g.now)}
                level={g.level}
                hint={`Now ${g.gauge.format(g.now)}, worst in this window ${g.gauge.format(g.worst)}`}
              />
            ))}
        </div>
      ) : null}
    </>
  )
}

export function ServersTile({ ctx, className }: { ctx: Context; className?: string }) {
  return (
    <Tile
      vendor="datadog"
      area="Infrastructure"
      title="Servers"
      aside="Now, with the worst point of the window marked"
      link={ctx.meta.links.metrics}
      onAsk={() =>
        ask(
          ctx,
          'Compare the servers of this instance: CPU, memory, disk, load and JVM heap. Say which one stands out and why.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.servers} skeleton={<RowsSkeleton rows={5} />}>
        {(v) => {
          if (!v.servers.length) return <Quiet muted>No server metrics in this window.</Quiet>

          return (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-3">
              {v.servers.map((s) => (
                <div key={s.host} className="bg-raised min-w-0 rounded-2xl p-3.5">
                  <div className="mb-3 flex items-center gap-2" title={s.host}>
                    <span
                      className={cn('size-2 shrink-0 rounded-full', STATE_DOT[serverLevel(s)])}
                    />
                    <span className="text-fg truncate text-[13px] font-medium">
                      {shortHost(s.host)}
                    </span>
                    <span className="text-brand-strong bg-brand-soft rounded-full px-1.5 py-px text-[10.5px] font-medium">
                      {s.role}
                    </span>
                  </div>
                  {Object.keys(s.metrics).length ? (
                    <Readings metrics={s.metrics} gauges={SERVER_GAUGES} />
                  ) : (
                    <div className="text-faint text-[12px]">No metrics from this server</div>
                  )}
                </div>
              ))}
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
      vendor="datadog"
      area="Database"
      title="Database"
      onAsk={() =>
        ask(
          ctx,
          'Check the database of this instance: CPU, free memory, storage, connections, read and write latency, active sessions and response time, Oracle session limit and tablespace use, and any database monitors or incidents. If the database is shared with other instances, say how much of the load is likely this one. Say what stands out and why.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.database} skeleton={<RowsSkeleton rows={5} />}>
        {(v) => {
          if (!v.databases.length) return <Quiet muted>No database metrics in this window.</Quiet>

          return (
            <div className="space-y-4">
              {v.databases.map((d) => (
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
                  {Object.keys(d.metrics).length ? (
                    <Readings metrics={d.metrics} gauges={DATABASE_GAUGES} />
                  ) : (
                    <div className="text-faint text-[12px]">No metrics from this database</div>
                  )}
                </div>
              ))}
            </div>
          )
        }}
      </Body>
    </Tile>
  )
}
