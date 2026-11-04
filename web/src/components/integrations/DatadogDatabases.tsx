import { Check as CheckIcon, Sparkle as SparklesIcon, X as XMarkIcon } from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import type { DatadogDatabase, DatadogDatabaseDiscovery, DatadogStatus } from '@shared/types.ts'
import { Dropdown } from '@/components/common/Dropdown'
import { Button, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { toggled } from '@/lib/collections'
import { onePerHost, useInstances } from '@/lib/instances'
import { useUnsavedWarning } from '@/lib/unsaved'

const same = (a: string[], b: string[]) => a.join() === b.join()

export function DatabaseChips({
  picked,
  catalog,
  onChange,
}: {
  picked: string[]
  catalog?: DatadogDatabase[]
  onChange: (ids: string[]) => void
}) {
  const engines = new Map((catalog ?? []).map((d) => [d.id, d.engine]))
  const options = (catalog ?? [])
    .filter((d) => !picked.includes(d.id))
    .map((d) => ({ value: d.id, label: d.id, hint: d.engine }))

  return (
    <div className="flex min-w-[200px] flex-1 flex-wrap items-center gap-1.5">
      {picked.map((id) => (
        <span
          key={id}
          className="text-text inline-flex h-7 items-center gap-1.5 rounded-full bg-white pr-1 pl-1.5 text-[12px]"
        >
          {engines.get(id) ? (
            <span className="bg-brand-soft text-brand-strong rounded-full px-1.5 text-[10.5px] font-medium">
              {engines.get(id)}
            </span>
          ) : null}
          {id}
          <button
            type="button"
            aria-label={`Remove ${id}`}
            onClick={() => onChange(picked.filter((p) => p !== id))}
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
          onChange={(id) => onChange([...picked, id].sort())}
        />
      ) : (
        <Skeleton className="h-8 w-32 rounded-full" />
      )}
    </div>
  )
}

function DatabaseSummary({ ids }: { ids: string[] }) {
  if (!ids.length)
    return <span className="text-faint min-w-0 flex-1 text-[12.5px]">No database</span>

  return <span className="text-text min-w-0 flex-1 truncate text-[12.5px]">{ids.join(', ')}</span>
}

export function DatadogDatabaseMatches({
  status,
  onSaved,
}: {
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
}) {
  const { instances } = useInstances()
  const [draft, setDraft] = useState<Record<string, string[]>>(status.databases)
  const [found, setFound] = useState<DatadogDatabaseDiscovery>()
  const [catalog, setCatalog] = useState<DatadogDatabase[]>()
  const [busy, setBusy] = useState<'detect' | 'save'>()
  const [error, setError] = useState<string>()
  const [editing, setEditing] = useState<Set<string>>(new Set())
  const aliases = useMemo(
    () => onePerHost(instances ?? []).map((i) => ({ alias: i.alias, host: i.host })),
    [instances],
  )

  const dirty = aliases.some((r) => !same(draft[r.alias] ?? [], status.databases[r.alias] ?? []))

  useEffect(() => setDraft(status.databases), [status.databases])
  useUnsavedWarning(dirty)

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
      const result = await api.datadogDiscoverDatabases()
      setFound(result)
      setCatalog(result.databases)
      setDraft((d) => {
        const next = { ...d }
        for (const [alias, ids] of Object.entries(result.groups))
          if (!next[alias]?.length) next[alias] = ids
        return next
      })
    })

  const edit = async (alias: string) => {
    setEditing((all) => toggled(all, alias))
    if (catalog) return

    await run('detect', async () => setCatalog((await api.datadogDatabases()).databases))
  }

  const save = () =>
    run('save', async () =>
      onSaved(await api.datadogPickDatabases({ ...status.databases, ...draft })),
    )

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13px] font-medium">Database per instance</div>
          <div className="text-muted text-[12px]">
            The database an instance runs on, such as its own RDS or a shared one. Detect suggests
            the one its servers' Oracle agent watches; check it before saving.
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          busy={busy === 'detect'}
          disabled={Boolean(busy)}
          onClick={() => void detect()}
        >
          <SparklesIcon className="size-3.5" />
          Detect databases
        </Button>
        <Button
          size="sm"
          variant="primary"
          busy={busy === 'save'}
          disabled={!dirty || Boolean(busy)}
          onClick={() => void save()}
        >
          <CheckIcon className="size-3.5" /> Save
        </Button>
      </div>
      <div className="divide-line border-line max-h-[380px] scrollbar-thin divide-y overflow-y-auto border-t">
        {!instances ? (
          <div className="space-y-3 px-5 py-4">
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : null}
        {aliases.map((r) => {
          const ids = draft[r.alias] ?? []
          const detected = found?.groups[r.alias]
          const open = editing.has(r.alias)

          return (
            <div key={r.alias} className="px-5 py-2.5">
              <div className="flex items-center gap-3">
                <span className="text-fg w-[220px] min-w-0 shrink-0 truncate text-[13px] font-medium">
                  {r.host}
                </span>
                <DatabaseSummary ids={ids} />
                {detected && !same(detected, ids) ? (
                  <button
                    type="button"
                    onClick={() => setDraft((d) => ({ ...d, [r.alias]: detected }))}
                    className="text-brand-strong hover:bg-brand-soft h-7 shrink-0 rounded-full px-2.5 text-[11.5px] font-medium"
                  >
                    Use {detected.join(', ')}
                  </button>
                ) : null}
                <Button size="sm" variant="ghost" onClick={() => void edit(r.alias)}>
                  {open ? 'Done' : 'Edit'}
                </Button>
              </div>
              {open ? (
                <div className="bg-raised mt-2 rounded-2xl p-2.5">
                  <DatabaseChips
                    picked={ids}
                    catalog={catalog}
                    onChange={(next) => setDraft((d) => ({ ...d, [r.alias]: next }))}
                  />
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
      {error ? (
        <div className="text-danger border-line border-t px-5 py-2.5 text-[12.5px]">{error}</div>
      ) : null}
    </div>
  )
}
