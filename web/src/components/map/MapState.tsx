import { ArrowsClockwise as ArrowPathIcon, MapTrifold as MapIcon } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { ActionsSkeleton, useSkeleton } from '@/components/common/skeletons'
import { Button, EmptyState, IconBadge, Select, Shimmer } from '@/components/common/ui'
import { instanceLabel } from '@/lib/instances'
import type { InstanceGraphState } from '@/lib/useInstanceGraph'

const GRAPH_ACTION_WIDTHS = ['w-[260px]', 'w-24']

function MapState({
  building,
  step,
  error,
  canBuild,
  onBuild,
}: {
  building: boolean
  step?: string
  error?: string
  canBuild: boolean
  onBuild: () => void
}) {
  return (
    <EmptyState
      badge={<IconBadge icon={MapIcon} size="lg" />}
      title={building ? <Shimmer>Reading the configuration</Shimmer> : 'No map yet'}
      error={error}
      action={
        building ? null : (
          <Button variant="primary" disabled={!canBuild} onClick={onBuild}>
            <MapIcon className="size-3.5" /> Build map
          </Button>
        )
      }
    >
      {building
        ? `${step ?? 'Starting'}. Large instances take a minute, or several when read from component exports.`
        : 'The Instance map and the Code explorer both read the map: how trackor types, fields, rules, automations, imports, reports and workflows link together, with their code. It is read with Test SQL when your account has it, otherwise from component exports and the API.'}
    </EmptyState>
  )
}

export function GraphPlaceholder({
  state,
  skeleton,
}: {
  state: InstanceGraphState
  skeleton: ReactNode
}) {
  const showSkeleton = useSkeleton(state.loading)
  if (showSkeleton) return skeleton
  if (state.loading) return null

  return (
    <div className="flex h-full items-center justify-center p-6">
      <MapState
        building={state.building}
        step={state.status?.step}
        error={state.error ?? state.status?.error}
        canBuild={Boolean(state.alias)}
        onBuild={() => void state.build()}
      />
    </div>
  )
}

export function BuildingNote({ step }: { step?: string }) {
  return <Shimmer tone="brand">{step ?? 'Building'}...</Shimmer>
}

export function GraphActions({ state }: { state: InstanceGraphState }) {
  if (!state.instances || state.loading) return <ActionsSkeleton widths={GRAPH_ACTION_WIDTHS} />

  return (
    <>
      <div className="w-[260px]">
        <Select
          className="w-full"
          value={state.alias}
          onChange={state.setAlias}
          placeholder={state.instances ? 'No signed-in instance' : 'Loading...'}
          options={state.signedIn.map((i) => ({ value: i.alias, label: instanceLabel(i) }))}
        />
      </div>
      {state.graph ? (
        <Button
          variant="primary"
          busy={state.building}
          disabled={!state.alias || state.building}
          onClick={() => void state.build()}
        >
          <ArrowPathIcon className="size-3.5" />
          Refresh
        </Button>
      ) : null}
    </>
  )
}
