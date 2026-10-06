import { MapIcon } from '@heroicons/react/24/outline'
import { Button, EmptyState, IconBadge, Spinner } from '@/components/ui'

export function MapState({
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
      badge={
        <IconBadge icon={MapIcon} size="lg">
          {building ? <Spinner className="size-6" /> : undefined}
        </IconBadge>
      }
      title={building ? 'Reading the configuration' : 'No map yet'}
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
        ? `${step ?? 'Starting'}. Large instances take about a minute.`
        : 'The Instance map and the Explorer both read the map: how trackor types, fields, rules, automations, imports, reports and workflows link together, with their code. Building it reads the configuration with read-only SQL and needs the Test SQL privilege.'}
    </EmptyState>
  )
}
