import { X as XMarkIcon } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import type { DatadogDatabase, DatadogDiscovery } from '@shared/types.ts'
import { Dropdown } from '@/components/common/Dropdown'
import { Button, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { hostsIn, roleOf, scopeOf, shortHost } from '@/lib/servers'

const SHOWN_HOSTS = 4

export type Matches = Record<string, string>
export type Databases = Record<string, string[]>

export const sameList = (a: string[], b: string[]) => a.join() === b.join()

function Tag({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <span className="bg-raised text-text inline-flex h-6 max-w-full shrink-0 items-center gap-1.5 rounded-full px-2 text-[12px]">
      {label ? <span className="text-brand-strong text-[10.5px] font-medium">{label}</span> : null}
      <span className="truncate">{children}</span>
    </span>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <span className="text-faint text-[12.5px]">{children}</span>
}

export function ServersShown({ scope }: { scope: string }) {
  if (!scope.trim()) return <Empty>No servers</Empty>

  const hosts = hostsIn(scope)
  if (!hosts)
    return (
      <span className="text-text block truncate font-mono text-[11.5px]" title={scope}>
        {scope}
      </span>
    )

  const extra = hosts.length - SHOWN_HOSTS

  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1" title={hosts.join('\n')}>
      {hosts.slice(0, SHOWN_HOSTS).map((h) => (
        <Tag key={h}>{shortHost(h)}</Tag>
      ))}
      {extra > 0 ? <span className="text-muted text-[11.5px]">+{extra}</span> : null}
    </span>
  )
}

export function DatabasesShown({ ids, catalog }: { ids: string[]; catalog?: DatadogDatabase[] }) {
  if (!ids.length) return <Empty>No database</Empty>

  const engines = new Map((catalog ?? []).map((d) => [d.id, d.engine]))

  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1">
      {ids.map((id) => (
        <Tag key={id} label={engines.get(id)}>
          {id}
        </Tag>
      ))}
    </span>
  )
}

function Removable({
  label,
  title,
  onRemove,
  children,
}: {
  label?: string
  title: string
  onRemove: () => void
  children: ReactNode
}) {
  return (
    <span
      title={title}
      className="text-text inline-flex h-7 items-center gap-1.5 rounded-full bg-white pr-1 pl-2.5 text-[12px]"
    >
      {label ? <span className="text-brand-strong text-[10.5px] font-medium">{label}</span> : null}
      {children}
      <button
        type="button"
        aria-label={`Remove ${title}`}
        onClick={onRemove}
        className="text-faint hover:text-fg hover:bg-raised flex size-5 items-center justify-center rounded-full"
      >
        <XMarkIcon className="size-3" />
      </button>
    </span>
  )
}

export function ServerPicker({
  scope,
  hosts,
  onChange,
}: {
  scope: string
  hosts?: DatadogDiscovery['hosts']
  onChange: (scope: string) => void
}) {
  const picked = scope.trim() ? hostsIn(scope) : []
  const [custom, setCustom] = useState(picked === null)

  if (custom || picked === null)
    return (
      <div className="flex items-center gap-1.5">
        <input
          value={scope}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Any Datadog filter, e.g. service:name env:prod"
          spellCheck={false}
          className="border-line-strong focus:border-brand placeholder:text-faint h-8 min-w-0 flex-1 rounded-full border bg-white px-3.5 font-mono text-[12px] outline-none"
        />
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setCustom(false)
            if (picked === null) onChange('')
          }}
        >
          Pick servers
        </Button>
      </div>
    )

  const options = (hosts ?? [])
    .filter((h) => !picked.includes(h.name))
    .map((h) => ({ value: h.name, label: h.name, hint: h.role }))

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {picked.map((name) => (
        <Removable
          key={name}
          title={name}
          label={roleOf(name)}
          onRemove={() => onChange(scopeOf(picked.filter((h) => h !== name)))}
        >
          {shortHost(name)}
        </Removable>
      ))}
      {hosts ? (
        <Dropdown
          variant="plain"
          searchable
          value=""
          placeholder={picked.length ? 'Add server' : 'Pick servers'}
          options={options}
          onChange={(name) => onChange(scopeOf([...picked, name]))}
        />
      ) : (
        <Skeleton className="h-7 w-28 rounded-full" />
      )}
      <button
        type="button"
        onClick={() => setCustom(true)}
        className="text-faint hover:text-brand-strong px-1 text-[11.5px]"
      >
        Use a filter instead
      </button>
    </div>
  )
}

export function DatabasePicker({
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
    <div className="flex flex-wrap items-center gap-1.5">
      {picked.map((id) => (
        <Removable
          key={id}
          title={id}
          label={engines.get(id)}
          onRemove={() => onChange(picked.filter((p) => p !== id))}
        >
          {id}
        </Removable>
      ))}
      {catalog ? (
        <Dropdown
          variant="plain"
          searchable
          value=""
          placeholder={picked.length ? 'Add database' : 'Pick a database'}
          options={options}
          onChange={(id) => onChange([...picked, id].sort())}
        />
      ) : (
        <Skeleton className="h-7 w-28 rounded-full" />
      )}
    </div>
  )
}

export type Detected = {
  hosts: DatadogDiscovery['hosts']
  catalog: DatadogDatabase[]
  matches: Matches
  databases: Databases
}

export async function detect(current: Matches): Promise<Detected> {
  const servers = await api.datadogDiscover()
  const kept = Object.fromEntries(Object.entries(current).filter(([, scope]) => scope.trim()))
  const found = await api.datadogDiscoverDatabases({ ...servers.groups, ...kept })

  return {
    hosts: servers.hosts,
    catalog: found.databases,
    matches: servers.groups,
    databases: found.groups,
  }
}

export async function loadChoices(): Promise<Pick<Detected, 'hosts' | 'catalog'>> {
  const [servers, databases] = await Promise.all([api.datadogDiscover(), api.datadogDatabases()])
  return { hosts: servers.hosts, catalog: databases.databases }
}
