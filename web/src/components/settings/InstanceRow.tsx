import {
  ArrowClockwise as RecheckIcon,
  ClockCountdown as KeepIcon,
  DotsThree,
  Key as KeyIcon,
  Trash as TrashIcon,
} from '@phosphor-icons/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Instance } from '@shared/types.ts'
import { dialog } from '@/components/common/Dialog'
import { MenuItem } from '@/components/common/MenuItem'
import { reportError } from '@/components/common/Toasts'
import { Button, Chip, Shimmer, type Tone } from '@/components/common/ui'
import { PlatformLabel } from '@/components/settings/PlatformLabel'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useClickOutside } from '@/lib/hooks'
import { allowedLabels } from '@/lib/instances'
import { useLayer } from '@/lib/layers'
import { REMEMBER_DAYS, rememberedUntil, signInState } from '@/lib/signin'

const MENU_WIDTH = 232
const MENU_GAP = 6
const EDGE_PX = 8
const CHECK_SIGN_IN =
  'Checks that the web session still works and what this account can use. If it ended, you can sign in again.'

const DOT: Record<Tone, string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  danger: 'bg-danger',
  neutral: 'bg-line-strong',
  brand: 'bg-brand',
}

const STATUS: Record<Tone, string> = {
  ok: 'Signed in',
  warn: 'Expires soon',
  danger: 'Rejected',
  neutral: 'Signed out',
  brand: 'Signed in',
}

function Separator() {
  return <span aria-hidden className="bg-line-strong size-[3px] shrink-0 rounded-full" />
}

function TextButton({
  label,
  title,
  onClick,
}: {
  label: string
  title?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="text-brand-strong shrink-0 font-medium hover:underline"
    >
      {label}
    </button>
  )
}

function Access({ instance, onCheck }: { instance: Instance; onCheck: () => void }) {
  const { access } = instance
  if (access.checking) return <Shimmer>Checking</Shimmer>

  if (!instance.valid) return <span className="text-faint shrink-0">Sign in to check access</span>

  if (access.error)
    return (
      <>
        <span className="text-danger min-w-0 truncate" title={access.error}>
          {access.error}
        </span>
        <TextButton label="Check again" onClick={onCheck} />
      </>
    )

  if (signInState(instance).stage === 'unknown')
    return <TextButton label="Check sign-in" title={CHECK_SIGN_IN} onClick={onCheck} />

  if (!access.checkedAt)
    return (
      <>
        <span className="text-faint shrink-0">Access not checked yet</span>
        <TextButton label="Check" onClick={onCheck} />
      </>
    )

  const labels = allowedLabels(access)
  const missing = labels.filter((l) => !l.on).map((l) => l.label)

  return (
    <>
      {labels
        .filter((l) => l.on)
        .map(({ label }) => (
          <span
            key={label}
            className="bg-ok-soft text-ok shrink-0 rounded-md px-1.5 text-[10.5px] leading-4 font-medium"
          >
            {label}
          </span>
        ))}
      {missing.length ? (
        <span className="text-faint min-w-0 truncate" title="This account cannot use these here">
          No {missing.join(', ')}
        </span>
      ) : null}
    </>
  )
}

function RowAction({
  instance,
  busy,
  onSignIn,
}: {
  instance: Instance
  busy: boolean
  onSignIn: () => void
}) {
  const { stage } = signInState(instance)
  if (busy)
    return (
      <Button size="sm" variant="primary" busy disabled>
        Signing in
      </Button>
    )

  if (stage === 'soon')
    return (
      <Button
        size="sm"
        variant="ghost"
        className="bg-warn-soft hover:bg-warn-soft text-warn"
        onClick={onSignIn}
      >
        Renew
      </Button>
    )

  if (stage !== 'ended' && stage !== 'expired') return null

  return (
    <Button size="sm" variant="primary" onClick={onSignIn}>
      <KeyIcon className="size-3.5" />
      {instance.mode === 'token' ? 'Replace token' : 'Sign in'}
    </Button>
  )
}

function InstanceMenu({
  instance,
  onSignIn,
  onCheck,
  onChanged,
  onFailed,
}: {
  instance: Instance
  onSignIn: () => void
  onCheck: () => void
  onChanged: (list: Instance[]) => void
  onFailed: () => void
}) {
  const [anchor, setAnchor] = useState<DOMRect>()
  const [top, setTop] = useState(0)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const { stage } = signInState(instance)
  const name = instance.tenant ? `${instance.host} (${instance.tenant})` : instance.host
  const open = Boolean(anchor)
  const close = () => setAnchor(undefined)

  useLayoutEffect(() => {
    if (!anchor || !menu.current) return

    const height = menu.current.getBoundingClientRect().height
    const fits = anchor.bottom + MENU_GAP + height + EDGE_PX <= window.innerHeight
    setTop(fits ? anchor.bottom + MENU_GAP : Math.max(EDGE_PX, anchor.top - MENU_GAP - height))
  }, [anchor])

  useClickOutside([menu, trigger], close, open)
  useLayer(close, open)

  useEffect(() => {
    if (!open) return

    const onScroll = (e: Event) => !menu.current?.contains(e.target as Node) && close()
    document.addEventListener('scroll', onScroll, true)
    return () => document.removeEventListener('scroll', onScroll, true)
  }, [open])

  const act = (work: () => Promise<void> | void) => {
    close()
    void Promise.resolve(work()).catch(reportError)
  }

  const keep = async () => {
    try {
      onChanged(await api.rememberInstance(instance.alias))
    } catch (e) {
      onFailed()
      await dialog.alert(`Could not keep ${instance.host} signed in`, (e as Error).message)
    }
  }

  const remove = async () => {
    const ok = await dialog.confirm({
      title: `Remove ${name}?`,
      body: 'Signs out and forgets it on this computer. Threads, maps and Datadog matches are kept; sign in again to use it.',
      confirmLabel: 'Remove',
      tone: 'danger',
    })
    if (!ok) return

    try {
      onChanged(await api.removeInstance(instance.alias))
    } catch (e) {
      onFailed()
      await dialog.alert('Could not remove it', (e as Error).message)
    }
  }

  const needsSignIn = stage === 'ended' || stage === 'expired'
  const again = instance.mode === 'token' ? 'Replace API token' : 'Sign in again'
  const againHint =
    instance.mode === 'remembered'
      ? 'Makes a new token. The current one stays active in Admin > Auth Tokens until it expires.'
      : undefined

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label={`More for ${name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => (open ? close() : setAnchor(e.currentTarget.getBoundingClientRect()))}
        className={cn(
          'text-faint hover:text-fg hover:bg-raised flex size-8 shrink-0 items-center justify-center rounded-full transition-colors',
          open && 'bg-raised text-fg',
        )}
      >
        <DotsThree weight="bold" className="size-4.5" />
      </button>
      {anchor
        ? createPortal(
            <div
              ref={menu}
              role="menu"
              style={{ left: anchor.right - MENU_WIDTH, top, width: MENU_WIDTH }}
              className="border-line-strong/70 animate-pop fixed z-[200] rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
            >
              {needsSignIn ? null : (
                <MenuItem
                  icon={<KeyIcon className="size-4" />}
                  label={again}
                  title={againHint}
                  onClick={() => act(onSignIn)}
                />
              )}
              {instance.mode === 'session' && stage === 'ok' ? (
                <MenuItem
                  icon={<KeepIcon className="size-4" />}
                  label={`Keep signed in ${REMEMBER_DAYS} days`}
                  title={`Creates an API token in your name from this web session. You won't be asked again until ${rememberedUntil()}.`}
                  onClick={() => act(keep)}
                />
              ) : null}
              {instance.valid && instance.access.checkedAt ? (
                <MenuItem
                  icon={<RecheckIcon className="size-4" />}
                  label="Check access again"
                  onClick={() => act(onCheck)}
                />
              ) : null}
              <div className="bg-line mx-1 my-1 h-px" />
              <MenuItem
                icon={<TrashIcon className="size-4" />}
                label="Remove"
                danger
                onClick={() => act(remove)}
              />
            </div>,
            document.body,
          )
        : null}
    </>
  )
}

export function InstanceRow({
  instance,
  busy,
  onSignIn,
  onCheck,
  onChanged,
  onFailed,
}: {
  instance: Instance
  busy: boolean
  onSignIn: () => void
  onCheck: () => void
  onChanged: (list: Instance[]) => void
  onFailed: () => void
}) {
  const state = signInState(instance)
  const tone = state.chip?.tone

  return (
    <div className="flex min-h-[52px] items-center gap-3 py-2 pr-3 pl-5">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span
            title={tone ? STATUS[tone] : 'Not checked recently'}
            className={cn(
              'size-2 shrink-0 rounded-full',
              tone ? DOT[tone] : 'ring-faint ring-[1.5px] ring-inset',
            )}
          />
          <span className="text-fg min-w-0 truncate text-[13px] font-medium">{instance.host}</span>
          {instance.tenant ? <Chip tone="brand">{instance.tenant}</Chip> : null}
          <PlatformLabel instance={instance} />
        </div>
        <div className="text-muted mt-0.5 ml-4 flex min-w-0 items-center gap-1.5 text-[11.5px]">
          <span
            title={state.summary}
            className={cn('shrink-0 whitespace-nowrap', tone === 'warn' && 'text-warn font-medium')}
          >
            {state.summary}
          </span>
          <Separator />
          <Access instance={instance} onCheck={onCheck} />
        </div>
      </div>
      <RowAction instance={instance} busy={busy} onSignIn={onSignIn} />
      <InstanceMenu
        instance={instance}
        onSignIn={onSignIn}
        onCheck={onCheck}
        onChanged={onChanged}
        onFailed={onFailed}
      />
    </div>
  )
}
