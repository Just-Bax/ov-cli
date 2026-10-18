import {
  Check as CheckIcon,
  Sparkle as SparklesIcon,
  Copy as Square2StackIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import type { DatadogArea, DatadogDiscovery, DatadogStatus } from '@shared/types.ts'
import datadogMark from '@/assets/datadog.svg'
import { Dropdown } from '@/components/common/Dropdown'
import { Button, IconBadge, Select, Skeleton, useCopy } from '@/components/common/ui'
import {
  ConnectModal,
  type ConnectProps,
  IntegrationAccountRow,
  IntegrationCard,
  KeyField,
  useConnect,
} from '@/components/integrations/parts'
import { api } from '@/lib/api'
import { toggled } from '@/lib/collections'
import { onePerHost, useInstances } from '@/lib/instances'
import { useLoad } from '@/lib/hooks'
import { hostsIn, roleOf, scopeOf, shortHost } from '@/lib/servers'
import { useUnsavedWarning } from '@/lib/unsaved'

export const DATADOG_PURPLE = '#632CA6'
const DEFAULT_SITE = 'datadoghq.com'
const DEFAULT_APP_HOST = 'app.datadoghq.com'

const AREA_LABELS: Record<DatadogArea, string> = {
  logs: 'Logs',
  metrics: 'Metrics',
  monitors: 'Monitors',
  events: 'Events',
  apm: 'APM',
  hosts: 'Hosts',
}

function siteAddress(status: DatadogStatus): string {
  return status.sites.find((s) => s.id === status.site)?.app ?? status.site
}

export function DatadogBadge({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <IconBadge size={size} color={DATADOG_PURPLE}>
      <img src={datadogMark} alt="Datadog" className={size === 'lg' ? 'size-7' : 'size-6'} />
    </IconBadge>
  )
}

export function useDatadog() {
  const { value: status, setValue: setStatus } = useLoad(api.datadog, [])
  return { status, setStatus }
}

function ScopesHint({ scopes }: { scopes: string[] }) {
  const [copied, copy] = useCopy()

  return (
    <div className="bg-raised rounded-2xl px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="text-fg text-[12.5px] font-medium">
          Read-only scopes for the application key
        </span>
        <button
          type="button"
          onClick={() => copy(scopes.join(' '))}
          className="text-brand-strong hover:bg-brand-soft ml-auto inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px] font-medium"
        >
          {copied ? <CheckIcon className="size-3" /> : <Square2StackIcon className="size-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {scopes.map((s) => (
          <span
            key={s}
            className="text-text inline-flex h-6 items-center rounded-full bg-white px-2.5 font-mono text-[11px]"
          >
            {s}
          </span>
        ))}
      </div>
      <div className="text-muted mt-2 text-[11.5px] leading-relaxed">
        Pick only these when creating the key. Anything left out is skipped, never an error.
      </div>
    </div>
  )
}

export function DatadogConnectModal({
  open,
  status,
  onClose,
  onConnected,
}: ConnectProps<DatadogStatus>) {
  const [site, setSite] = useState(status?.site ?? DEFAULT_SITE)
  const [apiKey, setApiKey] = useState('')
  const [appKey, setAppKey] = useState('')
  const { busy, error, setError, submit } = useConnect(
    () => api.datadogConnect(site, apiKey, appKey),
    onConnected,
  )

  useEffect(() => {
    if (!open) return
    setSite(status?.site ?? DEFAULT_SITE)
    setApiKey('')
    setAppKey('')
    setError(undefined)
  }, [open])

  const app = `https://${status?.sites.find((s) => s.id === site)?.app ?? DEFAULT_APP_HOST}`

  return (
    <ConnectModal
      open={open}
      busy={busy}
      badge={<DatadogBadge />}
      title="Connect Datadog"
      subtitle="Logs, metrics, monitors and events for your instances, read-only."
      error={error}
      busyLabel="Checking keys"
      ready={Boolean(apiKey.trim() && appKey.trim())}
      onClose={onClose}
      onSubmit={() => void submit()}
      privacy="Keys stay in this computer's credential store and are only sent to Datadog. Your Datadog admins can see application keys and may audit their use. Logs the agent reads in a thread are sent to GitHub Copilot like any other tool result."
    >
      <div>
        <div className="text-fg text-[13px] font-medium">Site</div>
        <Select
          className="mt-1.5 w-full"
          value={site}
          onChange={setSite}
          options={(status?.sites ?? []).map((s) => ({
            value: s.id,
            label: s.app,
            hint: s.id === DEFAULT_SITE ? 'Most accounts' : undefined,
          }))}
        />
        <div className="text-muted mt-1.5 px-1 text-[11.5px]">
          The address in your browser when you use Datadog. Most accounts use app.datadoghq.com.
        </div>
      </div>

      <KeyField
        label="API key"
        href={`${app}/organization-settings/api-keys`}
        linkLabel="Open API keys"
        value={apiKey}
        onChange={setApiKey}
        placeholder="32 characters"
        hint="Organization Settings > API Keys. Copy an existing key, or ask an admin for one. On its own it cannot read data."
      />
      <KeyField
        label="Application key"
        href={`${app}/personal-settings/application-keys`}
        linkLabel="Open application keys"
        value={appKey}
        onChange={setAppKey}
        placeholder="40 characters"
        hint="Personal Settings > Application Keys > New Key. It reads with your own permissions."
      />

      <ScopesHint scopes={status?.scopes ?? []} />
    </ConnectModal>
  )
}

function renderConnect(props: ConnectProps<DatadogStatus>) {
  return <DatadogConnectModal {...props} />
}

type Row = { alias: string; host: string }

function ServerSummary({ scope }: { scope: string }) {
  if (!scope.trim())
    return <span className="text-faint min-w-0 flex-1 text-[12.5px]">No servers</span>

  const hosts = hostsIn(scope)
  if (!hosts)
    return (
      <span className="text-text min-w-0 flex-1 truncate font-mono text-[12px]" title={scope}>
        {scope}
      </span>
    )

  const roles = new Map<string, number>()
  for (const h of hosts) roles.set(roleOf(h), (roles.get(roleOf(h)) ?? 0) + 1)

  return (
    <span className="flex min-w-0 flex-1 items-center gap-2" title={hosts.join('\n')}>
      {[...roles].map(([role, n]) => (
        <span
          key={role}
          className="bg-brand-soft text-brand-strong shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
        >
          {role} {n}
        </span>
      ))}
      <span className="text-muted min-w-0 truncate text-[12px]">
        {hosts.map(shortHost).join(', ')}
      </span>
    </span>
  )
}

export function ServerChips({
  scope,
  hosts,
  onChange,
}: {
  scope: string
  hosts: DatadogDiscovery['hosts']
  onChange: (scope: string) => void
}) {
  const picked = scope.trim() ? hostsIn(scope) : []
  const [custom, setCustom] = useState(Boolean(scope) && picked === null)
  if (custom || picked === null)
    return (
      <div className="flex min-w-[200px] flex-1 items-center gap-1.5">
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
          Servers
        </Button>
      </div>
    )

  const options = hosts
    .filter((h) => !picked.includes(h.name))
    .map((h) => ({ value: h.name, label: h.name, hint: h.role }))

  return (
    <div className="flex min-w-[200px] flex-1 flex-wrap items-center gap-1.5">
      {picked.map((name) => (
        <span
          key={name}
          title={name}
          className="bg-raised text-text inline-flex h-7 items-center gap-1.5 rounded-full pr-1 pl-1.5 text-[12px]"
        >
          <span className="bg-brand-soft text-brand-strong rounded-full px-1.5 text-[10.5px] font-medium">
            {roleOf(name)}
          </span>
          {shortHost(name)}
          <button
            type="button"
            aria-label={`Remove ${name}`}
            onClick={() => onChange(scopeOf(picked.filter((h) => h !== name)))}
            className="text-faint hover:text-fg flex size-5 items-center justify-center rounded-full hover:bg-white"
          >
            <XMarkIcon className="size-3" />
          </button>
        </span>
      ))}
      {hosts.length ? (
        <Dropdown
          variant="plain"
          searchable
          value=""
          placeholder={picked.length ? 'Add' : 'Pick servers'}
          options={options}
          onChange={(name) => onChange(scopeOf([...picked, name]))}
        />
      ) : null}
      <button
        type="button"
        onClick={() => setCustom(true)}
        className="text-faint hover:text-brand-strong px-1 text-[11.5px]"
      >
        Custom filter
      </button>
    </div>
  )
}

function DatadogMatches({
  status,
  onSaved,
}: {
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
}) {
  const { instances } = useInstances()
  const [draft, setDraft] = useState<Record<string, string>>(status.matches)
  const [found, setFound] = useState<DatadogDiscovery>()
  const [busy, setBusy] = useState<'detect' | 'save'>()
  const [error, setError] = useState<string>()
  const [editing, setEditing] = useState<Set<string>>(new Set())
  const rows: Row[] = useMemo(
    () => onePerHost(instances ?? []).map((i) => ({ alias: i.alias, host: i.host })),
    [instances],
  )

  const dirty = rows.some((r) => (draft[r.alias] ?? '') !== (status.matches[r.alias] ?? ''))
  const unclaimed = (found?.hosts ?? []).filter((h) => !h.alias).length

  useEffect(() => setDraft(status.matches), [status.matches])
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
      const result = await api.datadogDiscover()
      setFound(result)
      setDraft((d) => {
        const next = { ...d }
        for (const [alias, scope] of Object.entries(result.groups))
          if (!next[alias]) next[alias] = scope
        return next
      })
    })

  const save = () =>
    run('save', async () => onSaved(await api.datadogMatches({ ...status.matches, ...draft })))

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13px] font-medium">Servers per instance</div>
          <div className="text-muted text-[12px]">
            The Datadog hosts an instance runs on, such as its web and app servers and replicas.
            {found
              ? ` ${found.hosts.length} hosts in Datadog, ${unclaimed} not tied to a signed-in instance.`
              : ''}
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
          Detect servers
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
        {rows.map((r) => {
          const scope = draft[r.alias] ?? ''
          const detected = found?.groups[r.alias]
          const open = editing.has(r.alias)

          return (
            <div key={r.alias} className="px-5 py-2.5">
              <div className="flex items-center gap-3">
                <span className="text-fg w-[220px] min-w-0 shrink-0 truncate text-[13px] font-medium">
                  {r.host}
                </span>
                <ServerSummary scope={scope} />
                {detected && detected !== scope ? (
                  <button
                    type="button"
                    onClick={() => setDraft((d) => ({ ...d, [r.alias]: detected }))}
                    className="text-brand-strong hover:bg-brand-soft h-7 shrink-0 rounded-full px-2.5 text-[11.5px] font-medium"
                  >
                    Use {hostsIn(detected)?.length} detected
                  </button>
                ) : null}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditing((all) => toggled(all, r.alias))}
                >
                  {open ? 'Done' : 'Edit'}
                </Button>
              </div>
              {open ? (
                <div className="bg-raised mt-2 rounded-2xl p-2.5">
                  <ServerChips
                    scope={scope}
                    hosts={found?.hosts ?? []}
                    onChange={(next) => setDraft((d) => ({ ...d, [r.alias]: next }))}
                  />
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
      {error ? (
        <div className="text-danger border-line border-t px-5 py-2.5 text-[12.5px]">{error}</div>
      ) : null}
    </div>
  )
}

export function DatadogCard({
  status,
  setStatus,
}: {
  status?: DatadogStatus
  setStatus: (s: DatadogStatus) => void
}) {
  return (
    <IntegrationCard
      name="Datadog"
      badge={<DatadogBadge />}
      status={status}
      setStatus={setStatus}
      connectedDetail={siteAddress}
      idleDetail="Logs, metrics, monitors, events and APM for your instances."
      changeLabel="Change keys"
      areas={AREA_LABELS}
      keysTitle={(s) => `API key ...${s.apiKeyLast4}, application key ...${s.appKeyLast4}`}
      test={api.datadogTest}
      footer={(s) => (
        <div className="border-line border-t">
          <DatadogMatches status={s} onSaved={setStatus} />
        </div>
      )}
      renderConnect={renderConnect}
    />
  )
}

export function DatadogAccountRow({
  status,
  setStatus,
}: {
  status?: DatadogStatus
  setStatus: (s: DatadogStatus) => void
}) {
  return (
    <IntegrationAccountRow
      name="Datadog"
      badge={<DatadogBadge />}
      status={status}
      setStatus={setStatus}
      connectedDetail={(s) =>
        `Connected to ${siteAddress(s)} with keys ending ...${s.apiKeyLast4} and ...${s.appKeyLast4}`
      }
      disconnectBody="The keys are removed from this computer. Instance matches are kept for next time."
      disconnect={api.datadogDisconnect}
      renderConnect={renderConnect}
    />
  )
}
