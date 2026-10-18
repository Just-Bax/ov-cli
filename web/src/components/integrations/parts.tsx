import {
  ArrowsClockwise as ArrowPathIcon,
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  Check as CheckIcon,
  CaretDown as ChevronDownIcon,
  Eye as EyeIcon,
  EyeSlash as EyeSlashIcon,
  LinkBreak as LinkSlashIcon,
  Lock as LockClosedIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { dialog } from '@/components/common/Dialog'
import { reportError } from '@/components/common/Toasts'
import { Button, Card, Chip, Skeleton } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { useEnterTransition } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { timeAgo } from '@/lib/time'

type IntegrationStatus = {
  connected: boolean
  error?: string | null
  checkedAt?: number | null
  permissions: Record<string, boolean>
}

export type ConnectProps<S> = {
  open: boolean
  status?: S
  onClose: () => void
  onConnected: (status: S) => void
}

type RenderConnect<S> = (props: ConnectProps<S>) => ReactNode

function useOpen(name: string): [boolean, () => void] {
  const key = `ov-agent.integration-${name}`
  const [open, setOpen] = useState(() => localStorage.getItem(key) === '1')
  const toggle = () =>
    setOpen((v) => {
      localStorage.setItem(key, v ? '0' : '1')
      return !v
    })

  return [open, toggle]
}

function CollapseButton({ open, onClick }: { open: boolean; onClick: () => void }) {
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

export function ConnectModal({
  open,
  busy,
  badge,
  title,
  subtitle,
  error,
  privacy,
  busyLabel,
  ready,
  onClose,
  onSubmit,
  children,
}: {
  open: boolean
  busy: boolean
  badge: ReactNode
  title: string
  subtitle: string
  error?: string
  privacy: ReactNode
  busyLabel: string
  ready: boolean
  onClose: () => void
  onSubmit: () => void
  children: ReactNode
}) {
  const shown = useEnterTransition(open)
  useLayer(() => !busy && onClose(), open)

  if (!open) return null

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
        aria-label={title}
        className={cn(
          'modal-enter max-h-[calc(100vh-32px)] w-full max-w-[540px] scrollbar-thin overflow-x-hidden overflow-y-auto rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)]',
          shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-3 scale-[0.98] opacity-0',
        )}
      >
        <div className="flex items-start gap-3.5 px-5 pt-5">
          {badge}
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">{title}</div>
            <div className="text-muted mt-0.5 text-[12.5px] leading-relaxed">{subtitle}</div>
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
            if (ready && !busy) onSubmit()
          }}
        >
          {children}

          <div className="text-muted flex gap-2.5 px-1 text-[11.5px] leading-relaxed">
            <LockClosedIcon className="mt-0.5 size-3.5 shrink-0" />
            <span>{privacy}</span>
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
            <Button type="submit" variant="primary" size="lg" busy={busy} disabled={!ready || busy}>
              <CheckIcon className="size-4" />
              {busy ? busyLabel : 'Test and connect'}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}

export function useConnect<S>(connect: () => Promise<S>, onConnected: (status: S) => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      onConnected(await connect())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return { busy, error, setError, submit }
}

function PermissionChips({
  labels,
  permissions,
}: {
  labels: Record<string, string>
  permissions: Record<string, boolean>
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(labels).map(([area, label]) =>
        permissions[area] ? (
          <Chip key={area} tone="ok">
            <CheckIcon className="size-3" /> {label}
          </Chip>
        ) : (
          <Chip key={area} tone="neutral" className="text-faint">
            {label}
          </Chip>
        ),
      )}
    </div>
  )
}

export function IntegrationCard<S extends IntegrationStatus>({
  name,
  badge,
  status,
  setStatus,
  connectedDetail,
  idleDetail,
  changeLabel,
  areas,
  keysTitle,
  test,
  details,
  footer,
  renderConnect,
}: {
  name: string
  badge: ReactNode
  status?: S
  setStatus: (status: S) => void
  connectedDetail: (status: S) => string
  idleDetail: string
  changeLabel: string
  areas: Record<string, string>
  keysTitle: (status: S) => string
  test: () => Promise<S>
  details?: ReactNode
  footer?: (status: S) => ReactNode
  renderConnect: RenderConnect<S>
}) {
  const [connecting, setConnecting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [open, toggle] = useOpen(name.toLowerCase())

  if (!status)
    return (
      <Card className="p-5">
        <Skeleton className="h-10 w-2/3 rounded-full" />
      </Card>
    )

  const runTest = () => {
    setTesting(true)
    test()
      .then(setStatus, reportError)
      .finally(() => setTesting(false))
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3.5 p-5">
        {badge}
        <div
          className={cn('mr-4 min-w-0 flex-1', status.connected && 'cursor-pointer')}
          onClick={status.connected ? toggle : undefined}
        >
          <div className="flex items-center gap-2">
            <span className="text-fg text-[14px] font-semibold">{name}</span>
            {status.connected ? (
              status.error ? (
                <Chip tone="danger">Needs attention</Chip>
              ) : (
                <Chip tone="ok">Connected</Chip>
              )
            ) : null}
          </div>
          <div className="text-muted mt-0.5 truncate text-[12.5px]">
            {status.connected ? connectedDetail(status) : idleDetail}
          </div>
        </div>
        {status.connected ? (
          <div className="flex shrink-0 gap-1">
            <Button size="sm" variant="ghost" busy={testing} disabled={testing} onClick={runTest}>
              <ArrowPathIcon className="size-3.5" /> Test
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConnecting(true)}>
              {changeLabel}
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
            <PermissionChips labels={areas} permissions={status.permissions} />
            {status.checkedAt ? (
              <span
                className="text-faint ml-auto text-[12px] whitespace-nowrap"
                title={keysTitle(status)}
              >
                Checked {timeAgo(status.checkedAt)}
              </span>
            ) : null}
          </div>
          {details}
          {status.error ? (
            <div className="border-line text-danger border-t px-5 py-2.5 text-[12.5px]">
              {status.error}
            </div>
          ) : null}
          {footer?.(status)}
        </>
      ) : null}
      {renderConnect({
        open: connecting,
        status,
        onClose: () => setConnecting(false),
        onConnected: (s) => {
          setStatus(s)
          setConnecting(false)
        },
      })}
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

export function IntegrationAccountRow<S extends IntegrationStatus>({
  name,
  badge,
  status,
  setStatus,
  connectedDetail,
  disconnectBody,
  disconnect,
  renderConnect,
}: {
  name: string
  badge: ReactNode
  status?: S
  setStatus: (status: S) => void
  connectedDetail: (status: S) => string
  disconnectBody: string
  disconnect: () => Promise<S>
  renderConnect: RenderConnect<S>
}) {
  const [connecting, setConnecting] = useState(false)

  const confirmDisconnect = async () => {
    const ok = await dialog.confirm({
      title: `Disconnect ${name}?`,
      body: disconnectBody,
      confirmLabel: 'Disconnect',
      tone: 'danger',
    })
    if (ok) setStatus(await disconnect())
  }

  return (
    <>
      <AccountRow
        badge={badge}
        title={name}
        detail={
          !status ? 'Loading...' : status.connected ? connectedDetail(status) : 'Not connected'
        }
        action={
          status?.connected ? (
            <Button
              size="sm"
              variant="danger"
              onClick={() => void confirmDisconnect().catch(reportError)}
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
      {renderConnect({
        open: connecting,
        status,
        onClose: () => setConnecting(false),
        onConnected: (s) => {
          setStatus(s)
          setConnecting(false)
        },
      })}
    </>
  )
}
