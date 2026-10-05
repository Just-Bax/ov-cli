import {
  ArrowPathIcon,
  CheckIcon,
  LinkSlashIcon,
  LockClosedIcon,
  SparklesIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Instance, PagerDutyArea, PagerDutyService, PagerDutyStatus } from '@shared/types.ts'
import pagerdutyMark from '@/assets/pagerduty.svg'
import { AccountRow, KeyField } from '@/components/datadog/Datadog'
import { dialog } from '@/components/Dialog'
import { Dropdown } from '@/components/Dropdown'
import { useInstances } from '@/components/InstancePicker'
import { Button, Card, Chip, IconBadge, Input, Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

export const PAGERDUTY_GREEN = '#06AC38'

const AREA_LABELS: Record<PagerDutyArea, string> = {
  incidents: 'Incidents',
  services: 'Services',
  oncall: 'On-call',
}

export function PagerDutyMark({ className }: { className?: string }) {
  return <img src={pagerdutyMark} alt="PagerDuty" className={cn('size-5', className)} />
}

export function PagerDutyBadge({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <IconBadge size={size} color={PAGERDUTY_GREEN}>
      <PagerDutyMark className={size === 'lg' ? 'size-6' : 'size-5'} />
    </IconBadge>
  )
}

export function usePagerDuty() {
  const [status, setStatus] = useState<PagerDutyStatus>()
  useEffect(() => {
    api
      .pagerduty()
      .then(setStatus)
      .catch(() => undefined)
  }, [])
  return { status, setStatus }
}

export function PagerDutyConnectModal({
  open,
  status,
  onClose,
  onConnected,
}: {
  open: boolean
  status?: PagerDutyStatus
  onClose: () => void
  onConnected: (status: PagerDutyStatus) => void
}) {
  const [account, setAccount] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [shown, setShown] = useState(false)

  useEffect(() => {
    if (!open) {
      setShown(false)
      return
    }
    setAccount(status?.subdomain ? `${status.subdomain}.pagerduty.com` : '')
    setApiKey('')
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
  const host = account
    .trim()
    .replace(/^https?:\/\//, '')
    .split('/')[0]
  const base = host.includes('pagerduty.com') ? `https://${host}` : 'https://app.pagerduty.com'

  const connect = async () => {
    setBusy(true)
    setError(undefined)
    try {
      onConnected(await api.pagerdutyConnect(account, apiKey))
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
        aria-label="Connect PagerDuty"
        className={cn(
          'max-h-[calc(100vh-32px)] w-full max-w-[540px] scrollbar-thin overflow-x-hidden overflow-y-auto rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)] transition-transform duration-150',
          shown ? 'scale-100' : 'scale-95',
        )}
      >
        <div className="flex items-start gap-3.5 px-5 pt-5">
          <PagerDutyBadge />
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">Connect PagerDuty</div>
            <div className="text-muted mt-0.5 text-[12.5px] leading-relaxed">
              Incidents and on-call for your instances, read-only.
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
            if (apiKey.trim() && !busy) void connect()
          }}
        >
          <div>
            <div className="text-fg text-[13px] font-medium">Account</div>
            <Input
              className="mt-1.5 w-full"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              placeholder="yourcompany.pagerduty.com, or paste any PagerDuty link"
            />
            <div className="text-muted mt-1.5 px-1 text-[11.5px]">
              Used for links and to pick the US or EU region. Leave empty for the US region.
            </div>
          </div>

          <KeyField
            label="API user token"
            href={`${base}/users`}
            linkLabel="Open PagerDuty"
            value={apiKey}
            onChange={setApiKey}
            placeholder="20 characters"
            hint="My Profile > User Settings > Create API User Token. It reads with your own permissions; OV Agent only reads."
          />

          <div className="text-muted flex gap-2.5 px-1 text-[11.5px] leading-relaxed">
            <LockClosedIcon className="mt-0.5 size-3.5 shrink-0" />
            <span>
              The token stays in this computer's credential store and is only sent to PagerDuty.
              Your PagerDuty admins can see and revoke user tokens. Incidents the agent reads in a
              run are sent to GitHub Copilot like any other tool result.
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
            <Button type="submit" variant="primary" size="lg" disabled={!apiKey.trim() || busy}>
              {busy ? <Spinner className="size-4" /> : <CheckIcon className="size-4" />}
              {busy ? 'Checking token' : 'Test and connect'}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}

function Permissions({ status }: { status: PagerDutyStatus }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {(Object.keys(AREA_LABELS) as PagerDutyArea[]).map((area) =>
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

// PagerDuty services belong to servers, not tenants: one row per host, under its main sign-in.
function hostRows(instances: Instance[] | undefined): Row[] {
  const byHost = new Map<string, Row>()
  const list = [...(instances ?? [])].sort(
    (a, b) => Number(Boolean(a.tenant)) - Number(Boolean(b.tenant)),
  )
  for (const i of list)
    if (!byHost.has(i.host)) byHost.set(i.host, { alias: i.alias, host: i.host })
  return [...byHost.values()].sort((a, b) => a.host.localeCompare(b.host))
}

export function PagerDutyMatches({
  status,
  onSaved,
}: {
  status: PagerDutyStatus
  onSaved: (s: PagerDutyStatus) => void
}) {
  const { instances } = useInstances()
  const rows = useMemo(() => hostRows(instances), [instances])
  const [services, setServices] = useState<PagerDutyService[]>()
  const [draft, setDraft] = useState<Record<string, string[]>>(status.matches)
  const [busy, setBusy] = useState<'load' | 'suggest' | 'save'>()
  const [error, setError] = useState<string>()

  useEffect(() => setDraft(status.matches), [status.matches])

  const load = async (suggest: boolean) => {
    setBusy(suggest ? 'suggest' : 'load')
    setError(undefined)
    try {
      const found = await api.pagerdutyServices()
      setServices(found.services)
      if (suggest)
        setDraft((d) => {
          const next = { ...d }
          for (const s of found.suggestions)
            if (!next[s.alias]?.length && s.services.length) next[s.alias] = s.services
          return next
        })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(undefined)
    }
  }

  useEffect(() => {
    if (status.permissions.services) void load(false)
  }, [])

  const byId = new Map((services ?? []).map((s) => [s.id, s]))
  const dirty = rows.some(
    (r) => (draft[r.alias] ?? []).join() !== (status.matches[r.alias] ?? []).join(),
  )
  const set = (alias: string, ids: string[]) => setDraft((d) => ({ ...d, [alias]: ids }))

  const save = async () => {
    setBusy('save')
    setError(undefined)
    try {
      onSaved(await api.pagerdutyMatches({ ...status.matches, ...draft }))
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
          <div className="text-fg text-[13px] font-medium">Instances</div>
          <div className="text-muted text-[12px]">
            The PagerDuty services that page for each instance. Tenants share their host's services.
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={Boolean(busy) || !status.permissions.services}
          onClick={() => void load(true)}
        >
          {busy === 'suggest' ? (
            <Spinner className="size-3.5" />
          ) : (
            <SparklesIcon className="size-3.5" />
          )}
          Suggest matches
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
      <div className="divide-line border-line max-h-[340px] scrollbar-thin divide-y overflow-y-auto border-t">
        {!instances || busy === 'load' ? (
          <div className="space-y-3 px-5 py-4">
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : (
          rows.map((r) => {
            const picked = draft[r.alias] ?? []
            const options = (services ?? [])
              .filter((s) => !picked.includes(s.id))
              .map((s) => ({ value: s.id, label: s.name, hint: s.status }))
            return (
              <div key={r.alias} className="flex flex-wrap items-center gap-2.5 px-5 py-2.5">
                <span className="text-fg w-[240px] min-w-0 truncate text-[13px] font-medium">
                  {r.host}
                </span>
                <div className="flex min-w-[200px] flex-1 flex-wrap items-center gap-1.5">
                  {picked.map((id) => (
                    <span
                      key={id}
                      className="bg-raised text-text inline-flex h-7 items-center gap-1 rounded-full pr-1 pl-3 text-[12px]"
                    >
                      {byId.get(id)?.name ?? id}
                      <button
                        type="button"
                        aria-label="Remove service"
                        onClick={() =>
                          set(
                            r.alias,
                            picked.filter((x) => x !== id),
                          )
                        }
                        className="text-faint hover:text-fg flex size-5 items-center justify-center rounded-full hover:bg-white"
                      >
                        <XMarkIcon className="size-3" />
                      </button>
                    </span>
                  ))}
                  {services ? (
                    <Dropdown
                      variant="plain"
                      searchable
                      value=""
                      placeholder={picked.length ? 'Add' : 'Pick services'}
                      options={options}
                      onChange={(id) => set(r.alias, [...picked, id])}
                    />
                  ) : null}
                </div>
                {!picked.length ? (
                  <span className="text-faint w-[90px] shrink-0 text-right text-[11.5px]">
                    Not matched
                  </span>
                ) : null}
              </div>
            )
          })
        )}
      </div>
      {error ? (
        <div className="text-danger border-line border-t px-5 py-2.5 text-[12.5px]">{error}</div>
      ) : null}
    </div>
  )
}

export function PagerDutyCard({
  status,
  setStatus,
}: {
  status?: PagerDutyStatus
  setStatus: (s: PagerDutyStatus) => void
}) {
  const [connecting, setConnecting] = useState(false)
  const [testing, setTesting] = useState(false)

  if (!status)
    return (
      <Card className="p-5">
        <Skeleton className="h-10 w-2/3 rounded-full" />
      </Card>
    )

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3.5 p-5">
        <PagerDutyBadge />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-fg text-[14px] font-semibold">PagerDuty</span>
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
              ? `${status.webUrl.replace('https://', '')} - ${status.user} - token ...${status.keyLast4}${status.checkedAt ? ` - checked ${timeAgo(status.checkedAt)}` : ''}`
              : 'Incidents and on-call for your instances. The agent uses them in runs, and Health shows open incidents per instance.'}
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
                setStatus(await api.pagerdutyTest().finally(() => setTesting(false)))
              }}
            >
              {testing ? <Spinner className="size-3.5" /> : <ArrowPathIcon className="size-3.5" />}{' '}
              Test
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConnecting(true)}>
              Change token
            </Button>
          </div>
        ) : (
          <Button variant="secondary" onClick={() => setConnecting(true)}>
            Connect
          </Button>
        )}
      </div>
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
            <PagerDutyMatches status={status} onSaved={setStatus} />
          </div>
        </>
      ) : null}
      <PagerDutyConnectModal
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

export function PagerDutyAccountRow({
  status,
  setStatus,
}: {
  status?: PagerDutyStatus
  setStatus: (s: PagerDutyStatus) => void
}) {
  const [connecting, setConnecting] = useState(false)
  return (
    <>
      <AccountRow
        badge={<PagerDutyBadge />}
        title="PagerDuty"
        detail={
          !status
            ? 'Loading...'
            : status.connected
              ? `Signed in as ${status.user} on ${status.webUrl.replace('https://', '')}`
              : 'Not connected'
        }
        action={
          status?.connected ? (
            <Button
              size="sm"
              variant="danger"
              onClick={async () => {
                const ok = await dialog.confirm({
                  title: 'Disconnect PagerDuty?',
                  body: 'The token is removed from this computer. Instance matches are kept for next time.',
                  confirmLabel: 'Disconnect',
                  tone: 'danger',
                })
                if (ok) setStatus(await api.pagerdutyDisconnect())
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
      <PagerDutyConnectModal
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
