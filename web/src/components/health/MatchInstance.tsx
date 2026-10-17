import { Sparkle as SparklesIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { DatadogDiscovery, DatadogStatus } from '@shared/types.ts'
import { DatadogBadge, ServerChips } from '@/components/integrations/Datadog'
import { Button, Card } from '@/components/common/ui'
import { api } from '@/lib/api'
import { hostsIn, roleOf, shortHost } from '@/lib/servers'

export function MatchInstance({
  host,
  alias,
  status,
  onSaved,
}: {
  host: string
  alias: string
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
}) {
  const [found, setFound] = useState<DatadogDiscovery>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  const [filter, setFilter] = useState('')
  const [saving, setSaving] = useState(false)
  const label = host.split('.')[0]

  const detect = async () => {
    setLoading(true)
    setError(undefined)
    try {
      const result = await api.datadogDiscover()
      setFound(result)
      if (result.groups[alias]) setFilter(result.groups[alias])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(undefined)
    try {
      onSaved(await api.datadogMatches({ ...status.matches, [alias]: filter.trim() }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const detected = found?.groups[alias]
  const detectedHosts = detected ? (hostsIn(detected) ?? []) : []

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-4">
        <DatadogBadge />
        <div className="min-w-[240px] flex-1">
          <div className="text-fg text-[14px] font-semibold">Pick {host}'s servers in Datadog</div>
          <div className="text-muted mt-0.5 text-[12.5px]">
            Logs, traffic, server metrics, monitors and events need the Datadog hosts this instance
            runs on.
          </div>
        </div>
        {found ? null : (
          <Button
            size="sm"
            variant="primary"
            busy={loading}
            disabled={loading}
            onClick={() => void detect()}
          >
            <SparklesIcon className="size-3.5" />
            Detect servers
          </Button>
        )}
      </div>

      {found ? (
        <div className="mt-4 space-y-3">
          <div className="text-muted text-[12.5px]">
            {detected
              ? `Found ${detectedHosts.map((h) => `${shortHost(h)} (${roleOf(h)})`).join(', ')}.`
              : `No Datadog host name mentions ${label}. Pick its servers below.`}
          </div>
          <div className="flex flex-wrap items-start gap-3">
            <ServerChips scope={filter} hosts={found.hosts} onChange={setFilter} />
            <Button
              variant="primary"
              busy={saving}
              disabled={!filter.trim() || saving}
              onClick={() => void save()}
            >
              Save servers
            </Button>
          </div>
        </div>
      ) : null}
      {error ? <div className="text-danger mt-3 text-[12.5px]">{error}</div> : null}
    </Card>
  )
}
