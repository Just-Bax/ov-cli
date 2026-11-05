import {
  Check as CheckIcon,
  CaretDown as ChevronDownIcon,
  Sparkle as SparklesIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import type { DatadogStatus } from '@shared/types.ts'
import { Button, Skeleton } from '@/components/common/ui'
import {
  type Databases,
  DatabasePicker,
  DatabasesShown,
  type Detected,
  detect,
  loadChoices,
  type Matches,
  sameList,
  ServerPicker,
  ServersShown,
} from '@/components/integrations/DatadogPickers'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { onePerHost, useInstances } from '@/lib/instances'
import { hostsIn, shortHost } from '@/lib/servers'
import { useUnsavedWarning } from '@/lib/unsaved'

const GRID = 'grid grid-cols-[minmax(150px,1fr)_minmax(0,1.4fr)_minmax(0,1fr)_20px] gap-4'

type Row = { alias: string; host: string }

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function Suggestion({ text, onUse }: { text: string; onUse: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onUse()
      }}
      className="text-brand-strong mt-1 block max-w-full truncate text-left text-[11.5px] hover:underline"
    >
      Detected {text}. Use it
    </button>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-muted mb-1.5 text-[11.5px] font-medium">{label}</div>
      {children}
    </div>
  )
}

function detectNote(found: Detected, filled: number, differ: number): string {
  const unclaimed = found.hosts.filter((h) => !h.alias).length
  const parts = [
    `Found ${plural(found.hosts.length, 'server')} and ${plural(found.catalog.length, 'database')} in Datadog.`,
    filled ? `Filled ${plural(filled, 'empty pick')}.` : 'Nothing empty to fill.',
    differ ? `${plural(differ, 'saved pick')} differ from what was detected.` : '',
    unclaimed ? `${plural(unclaimed, 'server')} match no signed-in instance.` : '',
  ]

  return [...parts.filter(Boolean), 'Check before saving.'].join(' ')
}

export function DatadogInstanceMatches({
  status,
  onSaved,
}: {
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
}) {
  const { instances } = useInstances()
  const rows: Row[] = useMemo(
    () => onePerHost(instances ?? []).map((i) => ({ alias: i.alias, host: i.host })),
    [instances],
  )
  const [matches, setMatches] = useState<Matches>(status.matches)
  const [databases, setDatabases] = useState<Databases>(status.databases)
  const [choices, setChoices] = useState<Pick<Detected, 'hosts' | 'catalog'>>()
  const [found, setFound] = useState<Detected>()
  const [note, setNote] = useState<string>()
  const [open, setOpen] = useState<string>()
  const [busy, setBusy] = useState<'detect' | 'save'>()
  const [error, setError] = useState<string>()

  const scopeOf = (alias: string) => matches[alias] ?? ''
  const idsOf = (alias: string) => databases[alias] ?? []
  const serversChanged = (alias: string) => scopeOf(alias) !== (status.matches[alias] ?? '')
  const databaseChanged = (alias: string) => !sameList(idsOf(alias), status.databases[alias] ?? [])
  const changed = rows.filter((r) => serversChanged(r.alias) || databaseChanged(r.alias))

  useEffect(() => setMatches(status.matches), [status.matches])
  useEffect(() => setDatabases(status.databases), [status.databases])
  useUnsavedWarning(changed.length > 0)

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
      const result = await detect(matches)
      const emptyServers = rows.filter((r) => !scopeOf(r.alias).trim() && result.matches[r.alias])
      const emptyDatabases = rows.filter((r) => !idsOf(r.alias).length && result.databases[r.alias])
      const differ = rows.filter(
        (r) =>
          (scopeOf(r.alias).trim() &&
            result.matches[r.alias] &&
            result.matches[r.alias] !== scopeOf(r.alias)) ||
          (idsOf(r.alias).length &&
            result.databases[r.alias] &&
            !sameList(result.databases[r.alias], idsOf(r.alias))),
      ).length

      setFound(result)
      setChoices(result)
      setMatches((m) => ({
        ...m,
        ...Object.fromEntries(emptyServers.map((r) => [r.alias, result.matches[r.alias]])),
      }))
      setDatabases((d) => ({
        ...d,
        ...Object.fromEntries(emptyDatabases.map((r) => [r.alias, result.databases[r.alias]])),
      }))
      setNote(detectNote(result, emptyServers.length + emptyDatabases.length, differ))
    })

  const toggle = async (alias: string) => {
    setOpen(open === alias ? undefined : alias)
    if (choices) return

    try {
      setChoices(await loadChoices())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const discard = () => {
    setMatches(status.matches)
    setDatabases(status.databases)
    setNote(undefined)
  }

  const save = () =>
    run('save', async () => {
      let next = status
      if (rows.some((r) => serversChanged(r.alias)))
        next = await api.datadogMatches({ ...status.matches, ...matches })
      if (rows.some((r) => databaseChanged(r.alias)))
        next = await api.datadogPickDatabases({ ...status.databases, ...databases })
      setOpen(undefined)
      setNote(undefined)
      onSaved(next)
    })

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13px] font-medium">Servers and database per instance</div>
          <div className="text-muted text-[12px]">
            What each instance runs on in Datadog. Instance health and the agent read only what is
            saved here.
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          busy={busy === 'detect'}
          disabled={Boolean(busy) || !rows.length}
          onClick={() => void runDetect()}
        >
          <SparklesIcon className="size-3.5" />
          {busy === 'detect' ? 'Detecting' : 'Detect'}
        </Button>
      </div>

      {note ? (
        <div className="bg-brand-soft text-text mx-5 mb-3 rounded-2xl px-3.5 py-2 text-[12px]">
          {note}
        </div>
      ) : null}

      <div
        className={cn(
          GRID,
          'border-line text-faint border-t px-5 pt-2.5 pb-1.5 text-[11px] font-medium',
        )}
      >
        <span>Instance</span>
        <span>Servers</span>
        <span>Database</span>
        <span />
      </div>

      <div className="divide-line max-h-[520px] scrollbar-thin divide-y overflow-y-auto">
        {!instances ? (
          <div className="space-y-3 px-5 py-4">
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : null}

        {rows.map((r) => {
          const scope = scopeOf(r.alias)
          const ids = idsOf(r.alias)
          const isOpen = open === r.alias
          const suggestedScope = found?.matches[r.alias]
          const suggestedIds = found?.databases[r.alias]
          const unsaved = serversChanged(r.alias) || databaseChanged(r.alias)

          return (
            <div key={r.alias} className={cn(isOpen && 'bg-raised/60')}>
              <div
                onClick={() => void toggle(r.alias)}
                className={cn(GRID, 'hover:bg-raised/60 cursor-pointer items-start px-5 py-3')}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className="text-fg truncate text-[13px] font-medium">{r.host}</span>
                  {unsaved ? (
                    <span
                      title="Not saved yet"
                      className="bg-brand size-1.5 shrink-0 rounded-full"
                    />
                  ) : null}
                </span>
                <span className="min-w-0">
                  <ServersShown scope={scope} />
                  {suggestedScope && scope.trim() && suggestedScope !== scope ? (
                    <Suggestion
                      text={(hostsIn(suggestedScope) ?? []).map(shortHost).join(', ')}
                      onUse={() => setMatches((m) => ({ ...m, [r.alias]: suggestedScope }))}
                    />
                  ) : null}
                </span>
                <span className="min-w-0">
                  <DatabasesShown ids={ids} catalog={choices?.catalog} />
                  {suggestedIds && ids.length && !sameList(suggestedIds, ids) ? (
                    <Suggestion
                      text={suggestedIds.join(', ')}
                      onUse={() => setDatabases((d) => ({ ...d, [r.alias]: suggestedIds }))}
                    />
                  ) : null}
                </span>
                <button
                  type="button"
                  aria-label={isOpen ? `Close ${r.host}` : `Edit ${r.host}`}
                  aria-expanded={isOpen}
                  onClick={(e) => {
                    e.stopPropagation()
                    void toggle(r.alias)
                  }}
                  className="text-faint hover:text-fg mt-0.5 grid size-5 place-items-center rounded-full"
                >
                  <ChevronDownIcon
                    className={cn('size-3.5 transition-transform', isOpen && 'rotate-180')}
                  />
                </button>
              </div>

              {isOpen ? (
                <div className="grid gap-4 px-5 pb-4 md:grid-cols-2">
                  <Field label="Servers">
                    <ServerPicker
                      scope={scope}
                      hosts={choices?.hosts}
                      onChange={(next) => setMatches((m) => ({ ...m, [r.alias]: next }))}
                    />
                  </Field>
                  <Field label="Database">
                    <DatabasePicker
                      picked={ids}
                      catalog={choices?.catalog}
                      onChange={(next) => setDatabases((d) => ({ ...d, [r.alias]: next }))}
                    />
                  </Field>
                </div>
              ) : null}
            </div>
          )
        })}

        {instances && !rows.length ? (
          <div className="text-muted px-5 py-4 text-[12.5px]">
            Sign in to an instance first, in the Instances section above.
          </div>
        ) : null}
      </div>

      {changed.length ? (
        <div className="border-line bg-panel flex items-center gap-2 border-t px-5 py-2.5">
          <span className="text-text flex-1 text-[12.5px]">
            {plural(changed.length, 'instance')} changed, not saved yet
          </span>
          <Button size="sm" variant="ghost" disabled={Boolean(busy)} onClick={discard}>
            Discard
          </Button>
          <Button
            size="sm"
            variant="primary"
            busy={busy === 'save'}
            disabled={Boolean(busy)}
            onClick={() => void save()}
          >
            <CheckIcon className="size-3.5" /> Save
          </Button>
        </div>
      ) : null}

      {error ? (
        <div className="text-danger border-line border-t px-5 py-2.5 text-[12.5px]">{error}</div>
      ) : null}
    </div>
  )
}
