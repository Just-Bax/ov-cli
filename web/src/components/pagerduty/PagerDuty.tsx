import {
  Info as InformationCircleIcon,
  PencilSimple as PencilIcon,
  ArrowsClockwise as ArrowPathIcon,
  Check as CheckIcon,
  LinkBreak as LinkSlashIcon,
  Lock as LockClosedIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { PagerDutyArea, PagerDutyStatus } from '@shared/types.ts'
import pagerdutyMark from '@/assets/pagerduty.svg'
import { AccountRow, CollapseButton, KeyField, useOpen } from '@/components/datadog/Datadog'
import { dialog } from '@/components/Dialog'
import { Button, Card, Chip, IconBadge, Input, Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { useLayer } from '@/lib/layers'
import { cn } from '@/lib/cn'
import { reportError } from '@/components/Toasts'

const PAGERDUTY_GREEN = '#06AC38'
const DEFAULT_WEB_URL = 'https://app.pagerduty.com'

const CHANGES = ['Notes', 'Acknowledge', 'Resolve', 'Escalate', 'Reassign', 'Snooze']

const AREA_LABELS: Record<PagerDutyArea, string> = {
  incidents: 'Incidents',
  oncall: 'On-call',
}

function PagerDutyMark({ className }: { className?: string }) {
  return <img src={pagerdutyMark} alt="PagerDuty" className={cn('size-5', className)} />
}

function PagerDutyBadge({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <IconBadge size={size} color={PAGERDUTY_GREEN}>
      <PagerDutyMark className={size === 'lg' ? 'size-6' : 'size-5'} />
    </IconBadge>
  )
}

export function usePagerDuty() {
  const [status, setStatus] = useState<PagerDutyStatus>()

  useEffect(() => {
    api.pagerduty().then(setStatus).catch(reportError)
  }, [])

  return { status, setStatus }
}

function PagerDutyConnectModal({
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
    return () => cancelAnimationFrame(frame)
  }, [open])

  useLayer(() => !busy && onClose(), open)

  if (!open) return null

  const host = account
    .trim()
    .replace(/^https?:\/\//, '')
    .split('/')[0]
  const base = host.includes('pagerduty.com') ? `https://${host}` : DEFAULT_WEB_URL

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
        'fixed inset-0 z-[100] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px] transition-opacity duration-200',
        shown ? 'opacity-100' : 'opacity-0',
      )}
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Connect PagerDuty"
        className={cn(
          'ease-spring max-h-[calc(100vh-32px)] w-full max-w-[540px] scrollbar-thin overflow-x-hidden overflow-y-auto rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)] transition-[transform,opacity] duration-300',
          shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-6 scale-[0.97] opacity-0',
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

export function PagerDutyCard({
  status,
  setStatus,
}: {
  status?: PagerDutyStatus
  setStatus: (s: PagerDutyStatus) => void
}) {
  const [connecting, setConnecting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [open, toggle] = useOpen('pagerduty')

  if (!status)
    return (
      <Card className="p-5">
        <Skeleton className="h-10 w-2/3 rounded-full" />
      </Card>
    )

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3.5 p-5">
        <PagerDutyBadge />
        <div
          className={cn('mr-4 min-w-0 flex-1', status.connected && 'cursor-pointer')}
          onClick={status.connected ? toggle : undefined}
        >
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
          <div className="text-muted mt-0.5 truncate text-[12.5px]">
            {status.connected
              ? `${status.webUrl.replace('https://', '')} - ${status.user}`
              : 'Incidents and on-call for your instances.'}
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
                setStatus(await api.pagerdutyTest().finally(() => setTesting(false)))
              }}
            >
              {testing ? <Spinner className="size-3.5" /> : <ArrowPathIcon className="size-3.5" />}{' '}
              Test
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConnecting(true)}>
              Change token
            </Button>
            <CollapseButton open={open} onClick={toggle} />
          </div>
        ) : (
          <Button variant="secondary" onClick={() => setConnecting(true)}>
            Connect
          </Button>
        )}
      </div>
      {status.connected && open ? (
        <>
          <div className="border-line flex flex-wrap items-center gap-3 border-t px-5 py-3">
            <span className="text-muted text-[12px] font-medium">Can read</span>
            <Permissions status={status} />
            {status.checkedAt ? (
              <span
                className="text-faint ml-auto text-[12px] whitespace-nowrap"
                title={`Token ...${status.keyLast4}`}
              >
                Checked {timeAgo(status.checkedAt)}
              </span>
            ) : null}
          </div>
          <div
            className="border-line flex flex-wrap items-center gap-3 border-t px-5 py-3"
            title="Only in runs with Allow changes on, and each change waits for your Approve. Needs a full-access token."
          >
            <span className="text-muted inline-flex items-center gap-1 text-[12px] font-medium">
              Can change <InformationCircleIcon className="text-faint size-3.5" />
            </span>
            <div className="flex flex-wrap gap-1.5">
              {CHANGES.map((label) => (
                <Chip key={label} tone="brand">
                  <PencilIcon className="size-3" /> {label}
                </Chip>
              ))}
            </div>
          </div>
          {status.error ? (
            <div className="border-line text-danger border-t px-5 py-2.5 text-[12.5px]">
              {status.error}
            </div>
          ) : null}
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
