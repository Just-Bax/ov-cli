import { Sparkle as SparklesIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { DatadogStatus } from '@shared/types.ts'
import { Button } from '@/components/common/ui'
import { DatabaseChips } from '@/components/integrations/DatadogDatabases'
import { api } from '@/lib/api'
import { useLoad } from '@/lib/hooks'

export function DatabasePicker({
  alias,
  status,
  onSaved,
}: {
  alias: string
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
}) {
  const { value: catalog } = useLoad(api.datadogDatabases, [])
  const saved = status.databases[alias] ?? []
  const [picked, setPicked] = useState<string[]>(saved)
  const [busy, setBusy] = useState<'detect' | 'save'>()
  const [note, setNote] = useState<string>()
  const [error, setError] = useState<string>()
  const dirty = picked.join() !== saved.join()

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

  const detect = () =>
    run('detect', async () => {
      const ids = (await api.datadogDiscoverDatabases()).groups[alias] ?? []
      setNote(
        ids.length
          ? `Its servers' Oracle agent watches ${ids.join(', ')}. Check it before saving.`
          : 'No database found from its servers. Pick it below.',
      )
      if (ids.length) setPicked(ids)
    })

  const save = () =>
    run('save', async () =>
      onSaved(await api.datadogPickDatabases({ ...status.databases, [alias]: picked })),
    )

  return (
    <div className="bg-raised rounded-2xl p-3">
      <div className="text-muted mb-2 text-[12px]">
        {note ?? 'Pick the database this instance runs on, such as its own RDS or a shared one.'}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <DatabaseChips picked={picked} catalog={catalog?.databases} onChange={setPicked} />
        <Button
          size="sm"
          variant="ghost"
          busy={busy === 'detect'}
          disabled={Boolean(busy)}
          onClick={() => void detect()}
        >
          <SparklesIcon className="size-3.5" />
          Detect
        </Button>
        <Button
          size="sm"
          variant="primary"
          busy={busy === 'save'}
          disabled={!dirty || !picked.length || Boolean(busy)}
          onClick={() => void save()}
        >
          Save
        </Button>
      </div>
      {error ? <div className="text-danger mt-2 text-[12.5px]">{error}</div> : null}
    </div>
  )
}
