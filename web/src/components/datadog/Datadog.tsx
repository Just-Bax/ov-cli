import {
  Check,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  LockKeyhole,
  RefreshCw,
  Save,
  Sparkles,
  Unplug,
  X,
} from 'lucide-react'
import { type ReactNode, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { DatadogArea, DatadogDiscovery, DatadogStatus, Instance } from '@shared/types.ts'
import datadogMark from '@/assets/datadog.svg'
import { dialog } from '@/components/Dialog'
import { useInstances } from '@/components/InstancePicker'
import { Button, Card, Chip, Select, Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

export const DATADOG_PURPLE = '#632CA6'

export const siteAddress = (status: DatadogStatus) =>
  status.sites.find((s) => s.id === status.site)?.app ?? status.site

export const AREA_LABELS: Record<DatadogArea, string> = {
  logs: 'Logs',
  metrics: 'Metrics',
  monitors: 'Monitors',
  events: 'Events',
  apm: 'APM',
  hosts: 'Hosts',
}

export function DatadogMark({ className }: { className?: string }) {
  return <img src={datadogMark} alt="Datadog" className={cn('size-5', className)} />
}

export function DatadogBadge({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full',
        size === 'lg' ? 'size-12' : 'size-10',
      )}
      style={{ background: `${DATADOG_PURPLE}14` }}
    >
      <DatadogMark className={size === 'lg' ? 'size-7' : 'size-6'} />
    </span>
  )
}

export function useDatadog() {
  const [status, setStatus] = useState<DatadogStatus>()
  const load = () =>
    api
      .datadog()
      .then(setStatus)
      .catch(() => undefined)
  useEffect(() => {
    void load()
  }, [])
  return { status, setStatus, reload: load }
}

function KeyField({
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
          {linkLabel} <ExternalLink className="size-3" />
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
          {shown ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
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
  const [site, setSite] = useState(status?.site ?? 'datadoghq.com')
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
    setSite(status?.site ?? 'datadoghq.com')
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
  const app = `https://${status?.sites.find((s) => s.id === site)?.app ?? 'app.datadoghq.com'}`
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
            <X className="size-4" />
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
                hint: s.id === 'datadoghq.com' ? 'Most accounts' : undefined,
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
                  setTimeout(() => setCopied(false), 1500)
                }}
                className="text-brand-strong hover:bg-brand-soft ml-auto inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px] font-medium"
              >
                {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
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
            <LockKeyhole className="mt-0.5 size-3.5 shrink-0" />
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
              {busy ? <Spinner className="size-4" /> : <Check className="size-4" />}
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
            <Check className="size-3" /> {AREA_LABELS[area]}
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

function formatCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n)
}

type Row = { alias: string; host: string; tenant?: string }

export function DatadogMatches({
  status,
  onSaved,
  only,
}: {
  status: DatadogStatus
  onSaved: (s: DatadogStatus) => void
  only?: string
}) {
  const { instances } = useInstances()
  const [draft, setDraft] = useState<Record<string, string>>(status.matches)
  const [counts, setCounts] = useState<Record<string, number | 'busy' | 'error'>>({})
  const [why, setWhy] = useState<Record<string, string>>({})
  const [found, setFound] = useState<DatadogDiscovery>()
  const [discovering, setDiscovering] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const listId = useId()

  useEffect(() => setDraft(status.matches), [status.matches])

  const rows: Row[] = useMemo(
    () =>
      (instances ?? [])
        .filter((i: Instance) => !only || i.alias === only)
        .map((i) => ({ alias: i.alias, host: i.host, tenant: i.tenant ?? undefined }))
        .sort(
          (a, b) => a.host.localeCompare(b.host) || (a.tenant ?? '').localeCompare(b.tenant ?? ''),
        ),
    [instances, only],
  )

  const preview = (alias: string, filter: string) => {
    clearTimeout(timers.current[alias])
    if (!filter.trim()) {
      setCounts((c) => ({ ...c, [alias]: 0 }))
      return
    }
    setCounts((c) => ({ ...c, [alias]: 'busy' }))
    timers.current[alias] = setTimeout(() => {
      api
        .datadogCount(filter)
        .then((r) => setCounts((c) => ({ ...c, [alias]: r.count })))
        .catch(() => setCounts((c) => ({ ...c, [alias]: 'error' })))
    }, 600)
  }

  const discover = async () => {
    setDiscovering(true)
    setError(undefined)
    try {
      const result = await api.datadogDiscover()
      setFound(result)
      const next = { ...draft }
      for (const s of result.suggestions) {
        if (only && s.alias !== only) continue
        if (!next[s.alias] && s.filter) next[s.alias] = s.filter
        setWhy((w) => ({ ...w, [s.alias]: s.why }))
        setCounts((c) => ({ ...c, [s.alias]: s.count }))
      }
      setDraft(next)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDiscovering(false)
    }
  }

  const dirty = rows.some((r) => (draft[r.alias] ?? '') !== (status.matches[r.alias] ?? ''))

  const save = async () => {
    setSaving(true)
    setError(undefined)
    try {
      onSaved(await api.datadogMatches({ ...status.matches, ...draft }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13px] font-medium">
            {only ? 'Match this instance' : 'Instances'}
          </div>
          <div className="text-muted text-[12px]">
            The Datadog filter that selects each instance's servers, e.g. host:acme-app-* or
            service:acme.
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={discovering || !status.permissions.logs}
          onClick={() => void discover()}
        >
          {discovering ? <Spinner className="size-3.5" /> : <Sparkles className="size-3.5" />}
          Suggest matches
        </Button>
        <Button size="sm" variant="primary" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? <Spinner className="size-3.5" /> : <Save className="size-3.5" />} Save
        </Button>
      </div>
      <datalist id={listId}>
        {(found?.values ?? []).map((v) => (
          <option key={`${v.kind}:${v.value}`} value={`${v.kind}:${v.value}`}>
            {formatCount(v.count)} logs / 24h
          </option>
        ))}
      </datalist>
      <div className="divide-line border-line max-h-[340px] scrollbar-thin divide-y overflow-y-auto border-t">
        {!instances ? (
          <div className="space-y-3 px-5 py-4">
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : null}
        {rows.map((r) => {
          const value = draft[r.alias] ?? ''
          const count = counts[r.alias]
          return (
            <div key={r.alias} className="flex flex-wrap items-center gap-2.5 px-5 py-2.5">
              <div className="flex w-[260px] min-w-0 items-center gap-2">
                <span className="text-fg truncate text-[13px] font-medium">{r.host}</span>
                {r.tenant ? <Chip tone="brand">{r.tenant}</Chip> : null}
              </div>
              <input
                value={value}
                list={listId}
                onChange={(e) => {
                  setDraft((d) => ({ ...d, [r.alias]: e.target.value }))
                  setWhy((w) => ({ ...w, [r.alias]: '' }))
                  preview(r.alias, e.target.value)
                }}
                placeholder={r.tenant ? 'Same as the host' : 'host:name* or service:name'}
                spellCheck={false}
                className="border-line-strong focus:border-brand placeholder:text-faint h-9 min-w-[200px] flex-1 rounded-full border bg-white px-3.5 font-mono text-[12px] outline-none"
              />
              <span className="flex w-[150px] shrink-0 items-center justify-end gap-1.5 text-[11.5px]">
                {count === 'busy' ? (
                  <Spinner className="text-faint size-3" />
                ) : count === 'error' ? (
                  <span className="text-danger">Query failed</span>
                ) : typeof count === 'number' && value ? (
                  <span className={count ? 'text-ok' : 'text-warn'}>
                    {count ? `${formatCount(count)} logs / 24h` : 'No logs in 24h'}
                  </span>
                ) : (
                  <span className="text-faint">{why[r.alias] || (value ? '' : 'Not matched')}</span>
                )}
              </span>
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

  if (!status)
    return (
      <Card className="p-5">
        <Skeleton className="h-10 w-2/3 rounded-full" />
      </Card>
    )

  const header = (
    <div className="flex flex-wrap items-center gap-3.5 p-5">
      <DatadogBadge />
      <div className="min-w-0 flex-1">
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
        <div className="text-muted mt-0.5 text-[12.5px]">
          {status.connected
            ? `${siteAddress(status)} - keys ...${status.apiKeyLast4} and ...${status.appKeyLast4}${status.checkedAt ? ` - checked ${timeAgo(status.checkedAt)}` : ''}`
            : 'Logs, metrics, monitors, events and APM for your instances. The agent uses them in runs, and Health shows them per instance.'}
        </div>
      </div>
      {status.connected ? (
        <div className="flex gap-1">
          <Button
            size="sm"
            variant="ghost"
            disabled={testing}
            onClick={async () => {
              setTesting(true)
              setStatus(await api.datadogTest().finally(() => setTesting(false)))
            }}
          >
            {testing ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />} Test
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConnecting(true)}>
            Change keys
          </Button>
        </div>
      ) : (
        <Button variant="primary" onClick={() => setConnecting(true)}>
          Connect
        </Button>
      )}
    </div>
  )

  return (
    <Card className="overflow-hidden">
      {header}
      {status.connected ? (
        <>
          <div className="border-line flex flex-wrap items-center gap-3 border-t px-5 py-3">
            <span className="text-muted text-[12px] font-medium">Can read</span>
            <Permissions status={status} />
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
              <Unplug className="size-3.5" /> Disconnect
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
