import { Sparkle as SparklesIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { DatadogStatus } from '@shared/types.ts'
import { Button, Card } from '@/components/common/ui'
import {
  DatabasePicker,
  type Detected,
  detect,
  loadChoices,
  ServerPicker,
} from '@/components/integrations/DatadogPickers'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { SourceTag } from './tiles'

export function MatchInstance({
  host,
  alias,
  status,
  onSaved,
  className,
}: {
  host: string
  alias: string
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
  className?: string
}) {
  const [choices, setChoices] = useState<Pick<Detected, 'hosts' | 'catalog'>>()
  const [scope, setScope] = useState(status.matches[alias] ?? '')
  const [ids, setIds] = useState<string[]>(status.databases[alias] ?? [])
  const [note, setNote] = useState<string>()
  const [busy, setBusy] = useState<'detect' | 'save'>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    loadChoices()
      .then(setChoices)
      .catch((e: Error) => setError(e.message))
  }, [])

  const run = async (kind: 'detect' | 'save', work: () => Promise<void>) => {
    setBusy(kind)
    setError(undefined)
    try {
      await work()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(undefined)
    }
  }

  const runDetect = () =>
    run('detect', async () => {
      const found = await detect({ ...status.matches, [alias]: scope })
      const servers = scope.trim() ? scope : (found.matches[alias] ?? '')
      const databases = ids.length ? ids : (found.databases[alias] ?? [])
      setChoices(found)
      setScope(servers)
      setIds(databases)
      setNote(
        found.matches[alias]
          ? 'Detect filled what it found. Check it before saving.'
          : `No Datadog server name mentions ${host.split('.')[0]}. Pick its servers below.`,
      )
    })

  const save = () =>
    run('save', async () => {
      await api.datadogMatches({ ...status.matches, [alias]: scope.trim() })
      onSaved(await api.datadogPickDatabases({ ...status.databases, [alias]: ids }))
    })

  return (
    <Card className={cn('p-5', className)}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-[220px] flex-1">
          <SourceTag vendor="datadog" area="Setup" />
          <div className="text-fg mt-1 text-[14px] font-semibold">Pick what {host} runs on</div>
          <div className="text-muted mt-0.5 text-[12.5px]">
            Monitors, requests, servers and database need its Datadog servers. The same picks are in
            Settings.
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          busy={busy === 'detect'}
          disabled={Boolean(busy)}
          onClick={() => void runDetect()}
        >
          <SparklesIcon className="size-3.5" />
          Detect
        </Button>
      </div>

      {note ? <div className="text-muted mt-3 text-[12.5px]">{note}</div> : null}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="bg-raised min-w-0 rounded-2xl p-3">
          <div className="text-muted mb-1.5 text-[11.5px] font-medium">Servers</div>
          <ServerPicker scope={scope} hosts={choices?.hosts} onChange={setScope} />
        </div>
        <div className="bg-raised min-w-0 rounded-2xl p-3">
          <div className="text-muted mb-1.5 text-[11.5px] font-medium">Database</div>
          <DatabasePicker picked={ids} catalog={choices?.catalog} onChange={setIds} />
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        {error ? (
          <div className="text-danger flex-1 text-[12.5px]">{error}</div>
        ) : (
          <span className="flex-1" />
        )}
        <Button
          variant="primary"
          busy={busy === 'save'}
          disabled={!scope.trim() || Boolean(busy)}
          onClick={() => void save()}
        >
          Save
        </Button>
      </div>
    </Card>
  )
}
