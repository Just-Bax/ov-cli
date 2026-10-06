import {
  ArrowPathIcon,
  ArrowTopRightOnSquareIcon,
  CheckIcon,
  ChevronDownIcon,
  EyeIcon,
  EyeSlashIcon,
  LinkSlashIcon,
  LockClosedIcon,
  SparklesIcon,
  Square2StackIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { type ReactNode, useEffect, useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import type { DatadogArea, DatadogDiscovery, DatadogStatus } from '@shared/types.ts'
import datadogMark from '@/assets/datadog.svg'
import { dialog } from '@/components/Dialog'
import { Dropdown } from '@/components/Dropdown'
import { useInstances } from '@/components/InstancePicker'
import { Button, Card, Chip, IconBadge, Select, Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { hostsIn, roleOf, scopeOf, shortHost } from '@/lib/servers'
import { cn } from '@/lib/cn'
import { reportError } from '@/components/Toasts'

export const DATADOG_PURPLE = '#632CA6'
const DEFAULT_SITE = 'datadoghq.com'
const DEFAULT_APP_HOST = 'app.datadoghq.com'
const COPIED_FEEDBACK_MS = 1500

const siteAddress = (status: DatadogStatus) =>
  status.sites.find((s) => s.id === status.site)?.app ?? status.site

export const AREA_LABELS: Record<DatadogArea, string> = {
  logs: 'Logs',
  metrics: 'Metrics',
  monitors: 'Monitors',
  events: 'Events',
  apm: 'APM',
  hosts: 'Hosts',
}

export function useOpen(name: string): [boolean, () => void] {
  const key = `ov-agent.integration-${name}`
  const [open, setOpen] = useState(() => localStorage.getItem(key) === '1')

  return [
    open,
    () =>
      setOpen((v) => {
        localStorage.setItem(key, v ? '0' : '1')
        return !v
      }),
  ]
}

export function CollapseButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={open ? 'Collapse' : 'Expand'}
      aria-expanded={open}
      onClick={onClick}
      className="text-muted hover:text-fg hover:bg-raised flex size-8 shrink-0 items-center justify-center rounded-full transition-colors"
    >
      <ChevronDownIcon className={cn('size-4 transition-transform', open && 'rotate-180')} />
    </button>
  )
}

function DatadogMark({ className }: { className?: string }) {
  return <img src={datadogMark} alt="Datadog" className={cn('size-5', className)} />
}

export function DatadogBadge({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <IconBadge size={size} color={DATADOG_PURPLE}>
      <DatadogMark className={size === 'lg' ? 'size-7' : 'size-6'} />
    </IconBadge>
  )
}

export function useDatadog() {
  const [status, setStatus] = useState<DatadogStatus>()

  useEffect(() => {
    api.datadog().then(setStatus).catch(reportError)
  }, [])

  return { status, setStatus }
}

export function KeyField({
  label,
  hint,
  href,
  linkLabel,
  value,
  onChange,
  placeholder,
}: {
  label: string
  hint: ReactNode
  href: string
  linkLabel: string
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  const [shown, setShown] = useState(false)
  const id = useId()

  return (
    <div>
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-fg text-[13px] font-medium">
          {label}
        </label>
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-brand-strong ml-auto inline-flex items-center gap-1 text-[12px] font-medium hover:underline"
        >
          {linkLabel} <ArrowTopRightOnSquareIcon className="size-3" />
        </a>
      </div>
      <div className="border-line-strong focus-within:border-brand mt-1.5 flex h-10 items-center rounded-full border bg-white pr-1 pl-4">
        <input
          id={id}
          type={shown ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          className="placeholder:text-faint min-w-0 flex-1 bg-transparent font-mono text-[12.5px] outline-none"
        />
        <button
          type="button"
          aria-label={shown ? 'Hide key' : 'Show key'}
          onClick={() => setShown((s) => !s)}
          className="text-faint hover:text-fg hover:bg-raised flex size-8 items-center justify-center rounded-full"
        >
          {shown ? <EyeSlashIcon className="size-3.5" /> : <EyeIcon className="size-3.5" />}
        </button>
      </div>
      <div className="text-muted mt-1.5 px-1 text-[11.5px] leading-relaxed">{hint}</div>
    </div>
  )
}

export function DatadogConnectModal({
  open,
  status,
  onClose,
  onConnected,
}: {
  open: boolean
  status?: DatadogStatus
  onClose: () => void
  onConnected: (status: DatadogStatus) => void
}) {
  const [site, setSite] = useState(status?.site ?? DEFAULT_SITE)
  const [apiKey, setApiKey] = useState('')
  const [appKey, setAppKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [copied, setCopied] = useState(false)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    if (!open) {
      setShown(false)
      return
    }

    setSite(status?.site ?? DEFAULT_SITE)
    setApiKey('')
    setAppKey('')
    setError(undefined)
    const frame = requestAnimationFrame(() => setShown(true))
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose()
    window.addEventListener('keydown', onKey)

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!open) return null

  const app = `https://${status?.sites.find((s) => s.id === site)?.app ?? DEFAULT_APP_HOST}`
  const scopes = status?.scopes ?? []

  const connect = async () => {
    setBusy(true)
    setError(undefined)
    try {
      onConnected(await api.datadogConnect(site, apiKey, appKey))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div
      className={cn(
        'fixed inset-0 z-[100] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px] transition-opacity duration-150',
        shown ? 'opacity-100' : 'opacity-0',
      )}
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Connect Datadog"
        className={cn(
          'max-h-[calc(100vh-32px)] w-full max-w-[540px] scrollbar-thin overflow-x-hidden overflow-y-auto rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)] transition-transform duration-150',
          shown ? 'scale-100' : 'scale-95',
        )}
      >
        <div className="flex items-start gap-3.5 px-5 pt-5">
          <DatadogBadge />
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">Connect Datadog</div>
            <div className="text-muted mt-0.5 text-[12.5px] leading-relaxed">
              Logs, metrics, monitors and events for your instances, read-only.
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={busy}
            className="text-faint hover:text-fg hover:bg-raised -mt-1 -mr-1 flex size-8 items-center justify-center rounded-full transition-colors"
          >
            <XMarkIcon className="size-4" />
          </button>
        </div>

        <form
          className="space-y-4 px-5 pt-5"
          onSubmit={(e) => {
            e.preventDefault()
            if (apiKey.trim() && appKey.trim() && !busy) void connect()
          }}
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

          <div className="bg-raised rounded-2xl px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="text-fg text-[12.5px] font-medium">
                Read-only scopes for the application key
              </span>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(scopes.join(' '))
                  setCopied(true)
                  setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS)
                }}
                className="text-brand-strong hover:bg-brand-soft ml-auto inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px] font-medium"
              >
                {copied ? (
                  <CheckIcon className="size-3" />
                ) : (
                  <Square2StackIcon className="size-3" />
                )}
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

          <div className="text-muted flex gap-2.5 px-1 text-[11.5px] leading-relaxed">
            <LockClosedIcon className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Keys stay in this computer's credential store and are only sent to Datadog. Your
              Datadog admins can see application keys and may audit their use. Logs the agent reads
              in a run are sent to GitHub Copilot like any other tool result.
            </span>
          </div>

          {error ? (
            <div className="border-danger/25 bg-danger-soft/50 text-text rounded-2xl border px-3.5 py-2.5 text-[12.5px] leading-relaxed">
              {error}
            </div>
          ) : null}

          <div className="flex items-center justify-end gap-2 pb-5">
            <Button variant="ghost" size="lg" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              disabled={!apiKey.trim() || !appKey.trim() || busy}
            >
              {busy ? <Spinner className="size-4" /> : <CheckIcon className="size-4" />}
              {busy ? 'Checking keys' : 'Test and connect'}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}

function Permissions({ status }: { status: DatadogStatus }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {(Object.keys(AREA_LABELS) as DatadogArea[]).map((area) =>
        status.permissions[area] ? (
          <Chip key={area} tone="ok">
            <CheckIcon className="size-3" /> {AREA_LABELS[area]}
          </Chip>
        ) : (
          <Chip key={area} tone="neutral" className="text-faint">
            {AREA_LABELS[area]}
          </Chip>
        ),
      )}
    </div>
  )
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

  useEffect(() => setDraft(status.matches), [status.matches])

  const rows: Row[] = useMemo(() => {
    const byHost = new Map<string, Row>()
    const mainSignInsFirst = [...(instances ?? [])].sort(
      (a, b) => Number(Boolean(a.tenant)) - Number(Boolean(b.tenant)),
    )
    for (const i of mainSignInsFirst)
      if (!byHost.has(i.host)) byHost.set(i.host, { alias: i.alias, host: i.host })

    return [...byHost.values()].sort((a, b) => a.host.localeCompare(b.host))
  }, [instances])

  const [editing, setEditing] = useState<Set<string>>(new Set())
  const toggleEditing = (alias: string) =>
    setEditing((all) => {
      const next = new Set(all)
      if (next.has(alias)) next.delete(alias)
      else next.add(alias)
      return next
    })

  const detect = async () => {
    setBusy('detect')
    setError(undefined)
    try {
      const result = await api.datadogDiscover()
      setFound(result)
      setDraft((d) => {
        const next = { ...d }
        for (const [alias, scope] of Object.entries(result.groups))
          if (!next[alias]) next[alias] = scope
        return next
      })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(undefined)
    }
  }

  const dirty = rows.some((r) => (draft[r.alias] ?? '') !== (status.matches[r.alias] ?? ''))
  const unclaimed = (found?.hosts ?? []).filter((h) => !h.alias).length

  const save = async () => {
    setBusy('save')
    setError(undefined)
    try {
      onSaved(await api.datadogMatches({ ...status.matches, ...draft }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(undefined)
    }
  }

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
          disabled={Boolean(busy)}
          onClick={() => void detect()}
        >
          {busy === 'detect' ? (
            <Spinner className="size-3.5" />
          ) : (
            <SparklesIcon className="size-3.5" />
          )}
          Detect servers
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={!dirty || Boolean(busy)}
          onClick={() => void save()}
        >
          {busy === 'save' ? <Spinner className="size-3.5" /> : <CheckIcon className="size-3.5" />}{' '}
          Save
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
                <Button size="sm" variant="ghost" onClick={() => toggleEditing(r.alias)}>
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
  const [connecting, setConnecting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [open, toggle] = useOpen('datadog')

  if (!status)
    return (
      <Card className="p-5">
        <Skeleton className="h-10 w-2/3 rounded-full" />
      </Card>
    )

  const header = (
    <div className="flex items-center gap-3.5 p-5">
      <DatadogBadge />
      <div
        className={cn('mr-4 min-w-0 flex-1', status.connected && 'cursor-pointer')}
        onClick={status.connected ? toggle : undefined}
      >
        <div className="flex items-center gap-2">
          <span className="text-fg text-[14px] font-semibold">Datadog</span>
          {status.connected ? (
            status.error ? (
              <Chip tone="danger">Needs attention</Chip>
            ) : (
              <Chip tone="ok">Connected</Chip>
            )
          ) : null}
        </div>
        <div className="text-muted mt-0.5 truncate text-[12.5px]">
          {status.connected
            ? siteAddress(status)
            : 'Logs, metrics, monitors, events and APM for your instances.'}
        </div>
      </div>
      {status.connected ? (
        <div className="flex shrink-0 gap-1">
          <Button
            size="sm"
            variant="ghost"
            disabled={testing}
            onClick={async () => {
              setTesting(true)
              setStatus(await api.datadogTest().finally(() => setTesting(false)))
            }}
          >
            {testing ? <Spinner className="size-3.5" /> : <ArrowPathIcon className="size-3.5" />}{' '}
            Test
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConnecting(true)}>
            Change keys
          </Button>
          <CollapseButton open={open} onClick={toggle} />
        </div>
      ) : (
        <Button variant="secondary" onClick={() => setConnecting(true)}>
          Connect
        </Button>
      )}
    </div>
  )

  return (
    <Card className="overflow-hidden">
      {header}
      {status.connected && open ? (
        <>
          <div className="border-line flex flex-wrap items-center gap-3 border-t px-5 py-3">
            <span className="text-muted text-[12px] font-medium">Can read</span>
            <Permissions status={status} />
            {status.checkedAt ? (
              <span
                className="text-faint ml-auto text-[12px] whitespace-nowrap"
                title={`API key ...${status.apiKeyLast4}, application key ...${status.appKeyLast4}`}
              >
                Checked {timeAgo(status.checkedAt)}
              </span>
            ) : null}
          </div>
          {status.error ? (
            <div className="border-line text-danger border-t px-5 py-2.5 text-[12.5px]">
              {status.error}
            </div>
          ) : null}
          <div className="border-line border-t">
            <DatadogMatches status={status} onSaved={setStatus} />
          </div>
        </>
      ) : null}
      <DatadogConnectModal
        open={connecting}
        status={status}
        onClose={() => setConnecting(false)}
        onConnected={(s) => {
          setStatus(s)
          setConnecting(false)
        }}
      />
    </Card>
  )
}

export function AccountRow({
  badge,
  title,
  detail,
  action,
}: {
  badge: ReactNode
  title: string
  detail: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex items-center gap-3.5 px-5 py-4">
      {badge}
      <div className="min-w-0 flex-1">
        <div className="text-fg text-[13.5px] font-semibold">{title}</div>
        <div className="text-muted truncate text-[12.5px]">{detail}</div>
      </div>
      {action}
    </div>
  )
}

export function DatadogAccountRow({
  status,
  setStatus,
}: {
  status?: DatadogStatus
  setStatus: (s: DatadogStatus) => void
}) {
  const [connecting, setConnecting] = useState(false)

  return (
    <>
      <AccountRow
        badge={<DatadogBadge />}
        title="Datadog"
        detail={
          !status
            ? 'Loading...'
            : status.connected
              ? `Connected to ${siteAddress(status)} with keys ending ...${status.apiKeyLast4} and ...${status.appKeyLast4}`
              : 'Not connected'
        }
        action={
          status?.connected ? (
            <Button
              size="sm"
              variant="danger"
              onClick={async () => {
                const ok = await dialog.confirm({
                  title: 'Disconnect Datadog?',
                  body: 'The keys are removed from this computer. Instance matches are kept for next time.',
                  confirmLabel: 'Disconnect',
                  tone: 'danger',
                })
                if (ok) setStatus(await api.datadogDisconnect())
              }}
            >
              <LinkSlashIcon className="size-3.5" /> Disconnect
            </Button>
          ) : status ? (
            <Button size="sm" variant="secondary" onClick={() => setConnecting(true)}>
              Connect
            </Button>
          ) : null
        }
      />
      <DatadogConnectModal
        open={connecting}
        status={status}
        onClose={() => setConnecting(false)}
        onConnected={(s) => {
          setStatus(s)
          setConnecting(false)
        }}
      />
    </>
  )
}
