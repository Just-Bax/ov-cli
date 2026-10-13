import { ArrowsClockwise as ArrowPathIcon, Sparkle as SparklesIcon } from '@phosphor-icons/react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { ActionsSkeleton, useSkeleton } from '@/components/common/skeletons'
import { Button, Card, EmptyState, Page, Select, Skeleton } from '@/components/common/ui'
import { DatadogBadge, DatadogConnectModal, useDatadog } from '@/components/integrations/Datadog'
import { cn } from '@/lib/cn'
import { openDraft } from '@/lib/draft'
import { onePerHost, useInstances } from '@/lib/instances'
import { href } from '@/lib/route'
import { hostsIn } from '@/lib/servers'
import {
  type Context,
  EventsCard,
  FailedRunsCard,
  IncidentsCard,
  MonitorsCard,
  ServersCard,
  SlowEndpointsCard,
  Summary,
  TimelineCard,
  TopErrorsCard,
} from './cards'
import { RANGE_WORDS, RANGES, type Range, useHealth } from './data'
import { MatchInstance } from './MatchInstance'

const INSTANCE_KEY = 'ov-agent.health-instance'
const STAT_TILES = 6
const HEALTH_ACTION_WIDTHS = ['w-[260px]', 'w-[112px]', 'w-9', 'w-36']

function serverCount(scope: string): ReactNode {
  const hosts = hostsIn(scope)
  if (!hosts) return <span className="font-mono">{scope}</span>
  return `${hosts.length} server${hosts.length === 1 ? '' : 's'}`
}

function PageSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Card className="space-y-4 p-5">
        <div className="flex gap-4">
          <Skeleton className="size-12 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-64" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: STAT_TILES }, (_, i) => (
            <Skeleton key={i} className="h-[74px] rounded-2xl" />
          ))}
        </div>
      </Card>
      <Card className="p-5">
        <Skeleton className="h-[260px] w-full rounded-2xl" />
      </Card>
    </div>
  )
}

export function HealthPage() {
  const { status, setStatus } = useDatadog()
  const { instances } = useInstances()
  const signedIn = useMemo(() => onePerHost((instances ?? []).filter((i) => i.valid)), [instances])
  const [alias, setAlias] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const [range, setRange] = useState<Range>('24h')
  const [connecting, setConnecting] = useState(false)
  const [tick, setTick] = useState(0)
  const label = signedIn.find((i) => i.alias === alias)?.host ?? ''
  const enabled = Boolean(status?.connected)
  const refresh = `${tick}|${JSON.stringify(status?.matches ?? {})}`
  const { meta, metaError, slots, busy } = useHealth(alias, range, enabled, refresh)
  const showSkeleton = useSkeleton(enabled && Boolean(alias) && !meta && !metaError)

  useEffect(() => {
    if (!instances || signedIn.some((i) => i.alias === alias)) return
    const host = instances.find((i) => i.alias === alias)?.host
    setAlias((signedIn.find((i) => i.host === host) ?? signedIn[0])?.alias ?? '')
  }, [instances])

  useEffect(() => {
    if (alias) localStorage.setItem(INSTANCE_KEY, alias)
  }, [alias])

  const askAll = () =>
    openDraft({
      instance: alias,
      prompt: `Check the health of ${label} over the last ${RANGE_WORDS[range]}. Use PagerDuty incidents, Datadog monitors, events such as deploys and restarts, error logs grouped by pattern, traffic and latency, and server metrics. Line them up with failed OneVizion processes in the same window. Tell me what changed or is failing, the likely cause, and what to do.`,
    })

  const actions = !status ? (
    <ActionsSkeleton widths={HEALTH_ACTION_WIDTHS} />
  ) : status.connected ? (
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
        className="aspect-square px-0"
        aria-label="Refresh"
        disabled={busy || !alias}
        onClick={() => setTick((t) => t + 1)}
      >
        <ArrowPathIcon className={cn('size-3.5', busy && 'animate-spin')} />
      </Button>
      <Button variant="primary" disabled={!alias} onClick={askAll}>
        <SparklesIcon className="size-3.5" /> Ask the agent
      </Button>
    </>
  ) : null

  const subtitle =
    meta?.scope && label ? (
      <>
        {label} - {serverCount(meta.scope)}
        <a href={href({ page: 'settings' })} className="text-brand-strong hover:underline">
          Change servers
        </a>
      </>
    ) : (
      'Incidents, errors, latency and server metrics per instance.'
    )

  let body: ReactNode
  if (!status || (status.connected && !instances)) body = <PageSkeleton />
  else if (!status.connected)
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
          See each instance's incidents, error logs, slow endpoints and server metrics next to its
          failed OneVizion processes. Read-only, with your own keys.
        </EmptyState>
      </div>
    )
  else if (!alias)
    body = (
      <div className="text-muted flex h-full items-center justify-center p-6 text-[13px]">
        Sign in to an instance in Settings first.
      </div>
    )
  else if (metaError) body = <div className="text-danger p-6 text-[13px]">{metaError}</div>
  else if (!meta || showSkeleton) body = showSkeleton ? <PageSkeleton /> : null
  else {
    const ctx: Context = { meta, label, alias, range, slots }
    const matched = Boolean(meta.scope)
    body = (
      <div className="space-y-4 p-6">
        {matched ? null : (
          <MatchInstance host={label} alias={alias} status={status} onSaved={setStatus} />
        )}
        <Summary ctx={ctx} busy={busy} />
        <TimelineCard ctx={ctx} />
        <IncidentsCard ctx={ctx} />
        {matched ? <ServersCard ctx={ctx} /> : null}
        <div className="grid gap-4 xl:grid-cols-2">
          {matched ? <TopErrorsCard ctx={ctx} /> : null}
          <FailedRunsCard ctx={ctx} />
        </div>
        {matched ? (
          <div className="grid gap-4 xl:grid-cols-3">
            <SlowEndpointsCard ctx={ctx} />
            <MonitorsCard ctx={ctx} />
            <EventsCard ctx={ctx} />
          </div>
        ) : null}
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
