import { X as XMarkIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { DatadogStatus } from '@shared/types.ts'
import { Dropdown } from '@/components/common/Dropdown'
import { Button, Skeleton } from '@/components/common/ui'
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const dirty = picked.join() !== saved.join()

  const save = async (next: string[]) => {
    setBusy(true)
    setError(undefined)
    try {
      onSaved(await api.datadogPickDatabases({ ...status.databases, [alias]: next }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const options = (catalog?.databases ?? [])
    .filter((d) => !picked.includes(d.id))
    .map((d) => ({ value: d.id, label: d.id, hint: d.engine }))

  return (
    <div className="bg-raised rounded-2xl p-3">
      <div className="text-muted mb-2 text-[12px]">
        Pick the database this instance runs on, such as a shared one. Picked databases replace the
        ones found from its servers.
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {picked.map((id) => (
          <span
            key={id}
            className="text-text inline-flex h-7 items-center gap-1 rounded-full bg-white pr-1 pl-2.5 text-[12px]"
          >
            {id}
            <button
              type="button"
              aria-label={`Remove ${id}`}
              onClick={() => setPicked((all) => all.filter((p) => p !== id))}
              className="text-faint hover:text-fg hover:bg-raised flex size-5 items-center justify-center rounded-full"
            >
              <XMarkIcon className="size-3" />
            </button>
          </span>
        ))}
        {catalog ? (
          <Dropdown
            variant="plain"
            searchable
            value=""
            placeholder={picked.length ? 'Add' : 'Pick a database'}
            options={options}
            onChange={(id) => setPicked((all) => [...all, id])}
          />
        ) : (
          <Skeleton className="h-8 w-32 rounded-full" />
        )}
        <span className="flex-1" />
        {saved.length ? (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save([])}>
            Find from servers
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="primary"
          busy={busy}
          disabled={!dirty || !picked.length || busy}
          onClick={() => void save(picked)}
        >
          Save
        </Button>
      </div>
      {error ? <div className="text-danger mt-2 text-[12.5px]">{error}</div> : null}
    </div>
  )
}
