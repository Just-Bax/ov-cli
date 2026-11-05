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
import { IncidentsTile, MonitorsTile, Overview, PagerDutyOff } from './alerts'
import { RANGE_WORDS, RANGES, type Range, useHealth } from './data'
import { DatabaseTile, ServersTile } from './infra'
import { MatchInstance } from './MatchInstance'
import { MaintenanceTile } from './maintenance'
import { EndpointsTile, PerformanceTile } from './performance'
import type { Context } from './tiles'

const INSTANCE_KEY = 'ov-agent.health-instance'
const CHECK_CELLS = 6
const THIRD = 'col-span-12 xl:col-span-4'
const MAIN = 'col-span-12 xl:col-span-8'
const SIDE = 'col-span-12 xl:col-span-4'
const ALERTS_ROW = 'h-[420px]'
const TRAFFIC_ROW = 'h-[500px]'
const INFRA_ROW = 'h-[440px]'
const SKELETON_ROWS = [
  [THIRD, THIRD, THIRD].map((span) => `${span} ${ALERTS_ROW}`),
  [`${MAIN} ${TRAFFIC_ROW}`, `${SIDE} ${TRAFFIC_ROW}`],
  [`${MAIN} ${INFRA_ROW}`, `${SIDE} ${INFRA_ROW}`],
].flat()
const HEALTH_ACTION_WIDTHS = ['w-[260px]', 'w-[112px]', 'w-9', 'w-36']

function serverCount(scope: string): ReactNode {
  const hosts = hostsIn(scope)
  if (!hosts) return <span className="font-mono">{scope}</span>
  return `${hosts.length} server${hosts.length === 1 ? '' : 's'}`
}

function PageSkeleton() {
  return (
    <div className="grid grid-cols-12 gap-4 p-6">
      <Card className="col-span-12 space-y-4 p-5">
        <div className="flex gap-4">
          <Skeleton className="size-12 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-64" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
          {Array.from({ length: CHECK_CELLS }, (_, i) => (
            <Skeleton key={i} className="h-[58px] rounded-2xl" />
          ))}
        </div>
      </Card>
      {SKELETON_ROWS.map((className, i) => (
        <Card key={i} className={cn('p-5', className)}>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-2 h-4 w-40" />
        </Card>
      ))}
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
  const refresh = `${tick}|${JSON.stringify([status?.matches, status?.databases])}`
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
      prompt: `Check the health of ${label} over the last ${RANGE_WORDS[range]}. Start from what is alerting: PagerDuty incidents and Datadog monitors. Then check requests, p95 latency and error rate from APM, server and database metrics against their limits, and OneTeam maintenance such as deployments and restarts in the same window. Tell me what changed or is failing, the likely cause, and what to do.`,
    })

  const askWithoutDatadog = () =>
    openDraft({
      instance: alias,
      prompt: `Check the health of ${label || 'this instance'} over the last ${RANGE_WORDS[range]} using only the instance: failed or slow imports, reports, rules, automations and module runs, the error log, and anything stuck in queues. Tell me what is failing, since when, the likely cause, and what to do.`,
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
        busy={busy}
        disabled={busy || !alias}
        onClick={() => setTick((t) => t + 1)}
      >
        <ArrowPathIcon className="size-3.5" />
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
      'Alerts from PagerDuty and Datadog, then requests, servers and database per instance.'
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
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" onClick={() => setConnecting(true)}>
                Connect Datadog
              </Button>
              <Button variant="ghost" onClick={askWithoutDatadog}>
                <SparklesIcon className="size-3.5" /> Ask the agent instead
              </Button>
            </div>
          }
        >
          See each instance's Datadog monitors, requests, latency, servers and database next to its
          PagerDuty incidents. Read-only, with your own keys. Without Datadog, the agent can still
          check failed imports, reports, rules and module runs on the instance itself.
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
    const incidents =
      slots.incidents.state === 'unavailable' ? (
        <PagerDutyOff className={`${THIRD} ${ALERTS_ROW}`} />
      ) : (
        <IncidentsTile ctx={ctx} className={`${THIRD} ${ALERTS_ROW}`} />
      )

    body = (
      <div className="grid grid-cols-12 gap-4 p-6">
        <div className="col-span-12">
          <Overview ctx={ctx} matched={matched} />
        </div>
        {matched ? null : (
          <MatchInstance
            key={alias}
            host={label}
            alias={alias}
            status={status}
            onSaved={setStatus}
            className="col-span-12"
          />
        )}
        {incidents}
        {matched ? <MonitorsTile ctx={ctx} className={`${THIRD} ${ALERTS_ROW}`} /> : null}
        <MaintenanceTile ctx={ctx} className={`${THIRD} ${ALERTS_ROW}`} />
        {matched ? (
          <>
            <PerformanceTile ctx={ctx} className={`${MAIN} ${TRAFFIC_ROW}`} />
            <EndpointsTile ctx={ctx} className={`${SIDE} ${TRAFFIC_ROW}`} />
            <ServersTile ctx={ctx} className={`${MAIN} ${INFRA_ROW}`} />
            <DatabaseTile ctx={ctx} className={`${SIDE} ${INFRA_ROW}`} />
          </>
        ) : null}
      </div>
    )
  }

  return (
    <Page title="Instance health" subtitle={subtitle} actions={actions}>
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
