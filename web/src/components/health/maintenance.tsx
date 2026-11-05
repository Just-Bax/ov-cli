import { useState } from 'react'
import type { MaintenanceItem } from '@shared/types.ts'
import { Chip, type Tone } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { ready, type Slots } from './data'
import type { Check } from './signals'
import { ask, Body, type Context, Quiet, ShowAll, Tile, tileId } from './tiles'
import { plural } from '@/lib/text'

const CANCELLED = 'Cancelled'
const DONE = ['Completed', CANCELLED]
const IN_PROGRESS = 'In Progress'
const MAINTENANCE_ROWS = 5

type Phase = 'now' | 'planned' | 'done'

const PHASES: { phase: Phase; title: string }[] = [
  { phase: 'now', title: 'Happening now' },
  { phase: 'planned', title: 'Planned' },
  { phase: 'done', title: 'Last 30 days' },
]

const STATUS_TONE: Record<string, Tone> = {
  Completed: 'ok',
  Cancelled: 'neutral',
  'In Progress': 'warn',
  Scheduled: 'brand',
  'Pending Approval': 'brand',
}

function dayOf(ms: number): string {
  return new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function timeOf(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function maintenanceLabel(m: MaintenanceItem): string {
  const what = m.type || m.subject || m.key
  return m.version ? `${what} ${m.version}` : what
}

function phaseOf(m: MaintenanceItem, now: number): Phase {
  if (m.status === IN_PROGRESS) return 'now'
  if (
    m.status !== CANCELLED &&
    m.start !== null &&
    m.end !== null &&
    m.start <= now &&
    now <= m.end
  )
    return 'now'
  if (!DONE.includes(m.status) && (m.start === null || m.start > now)) return 'planned'
  return 'done'
}

export function maintenanceCheck(slots: Slots): Check {
  const slot = slots.maintenance
  const base = { key: 'maintenance', title: 'Maintenance' }
  if (slot.state === 'loading') return { ...base, state: 'loading', text: 'Checking' }
  if (slot.state === 'unavailable') return { ...base, state: 'off', text: slot.reason }
  if (slot.state === 'error') return { ...base, state: 'off', text: 'Could not read it' }

  const now = Date.now()
  const items = slot.value.items
  const current = items.find((m) => phaseOf(m, now) === 'now')
  if (current) return { ...base, state: 'warn', text: `${maintenanceLabel(current)} now` }

  const next = items
    .filter((m) => phaseOf(m, now) === 'planned')
    .sort((a, b) => (a.start ?? Infinity) - (b.start ?? Infinity))[0]
  if (next)
    return {
      ...base,
      state: 'ok',
      text: `Next ${next.start ? dayOf(next.start) : '(no date)'}: ${maintenanceLabel(next)}`,
    }

  const last = items.find((m) => m.status !== CANCELLED && m.start !== null)
  if (last)
    return { ...base, state: 'ok', text: `Last ${dayOf(last.start!)}: ${maintenanceLabel(last)}` }

  return { ...base, state: 'ok', text: 'None in 30 days' }
}

function Row({ m }: { m: MaintenanceItem }) {
  const details = [
    m.owner,
    m.downtimeMinutes ? `${m.downtimeMinutes} min downtime` : '',
    m.servers.length ? plural(m.servers.length, 'server') : '',
  ].filter(Boolean)

  return (
    <a
      href={m.url}
      target="_blank"
      rel="noreferrer"
      title={`${m.key}${m.subject ? `: ${m.subject}` : ''}\n${m.servers.join(', ')}`}
      className="hover:bg-raised flex items-center gap-3 rounded-2xl px-3 py-2"
    >
      <span className="w-14 shrink-0 text-[11px] leading-tight tabular-nums">
        {m.start ? (
          <>
            <span className="text-text block font-medium">{dayOf(m.start)}</span>
            <span className="text-faint block">{timeOf(m.start)}</span>
          </>
        ) : (
          <span className="text-faint block">No date</span>
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-fg block truncate text-[12.5px]">{maintenanceLabel(m)}</span>
        <span className="text-faint block truncate text-[11px]">{details.join(', ')}</span>
      </span>
      <Chip tone={STATUS_TONE[m.status] ?? 'neutral'}>{m.status}</Chip>
    </a>
  )
}

export function MaintenanceTile({ ctx, className }: { ctx: Context; className?: string }) {
  const [all, setAll] = useState(false)
  const data = ready(ctx.slots.maintenance)

  return (
    <Tile
      id={tileId('maintenance')}
      vendor="oneteam"
      area="Maintenance"
      title="Maintenance"
      aside="Deployments, restarts and database work"
      link={data?.webUrl}
      onAsk={() =>
        ask(
          ctx,
          'Review the OneTeam maintenance for this instance: what was deployed or restarted recently and what is planned, and whether any of it lines up with PagerDuty incidents, Datadog monitors or APM changes.',
        )
      }
      className={className}
    >
      <Body slot={ctx.slots.maintenance}>
        {(v) => {
          if (!v.items.length) return <Quiet>No maintenance in the last 30 days or planned.</Quiet>

          const now = Date.now()
          const ordered = PHASES.flatMap(({ phase }) =>
            v.items.filter((m) => phaseOf(m, now) === phase),
          )
          const shown = new Set(all ? ordered : ordered.slice(0, MAINTENANCE_ROWS))

          return (
            <div className="-mx-3 space-y-3">
              {PHASES.map(({ phase, title }) => {
                const rows = ordered.filter((m) => shown.has(m) && phaseOf(m, now) === phase)
                if (!rows.length) return null

                return (
                  <div key={phase}>
                    <div
                      className={cn(
                        'px-3 pb-1 text-[11px] font-medium',
                        phase === 'now' ? 'text-warn' : 'text-muted',
                      )}
                    >
                      {title}
                    </div>
                    {rows.map((m) => (
                      <Row key={m.key} m={m} />
                    ))}
                  </div>
                )
              })}
              <div className="px-1">
                <ShowAll
                  shown={MAINTENANCE_ROWS}
                  total={ordered.length}
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
