import {
  ArrowsClockwise as ArrowPathIcon,
  Check as CheckIcon,
  Globe as GlobeAltIcon,
  Info as InfoIcon,
  Key as KeyIcon,
  Lock as LockClosedIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { reportError } from '@/components/common/Toasts'
import { Button, Input, SWITCH_TRACK, SwitchKnob } from '@/components/common/ui'
import { LiveScreen, SCREEN_BAR_PX, screenSize } from '@/components/screen/LiveScreen'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useEnterTransition } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { MINUTE_MS, SECOND_MS } from '@/lib/time'
import { hostOf } from '@/lib/url'

type SignInMethod = 'browser' | 'token'

export type SignInTarget = { url: string; host: string; tenant?: string; mode?: SignInMethod }

type SignInSubmit = (
  target: SignInTarget,
  token?: string,
  screen?: { width: number; height: number },
  remember?: boolean,
) => Promise<{ ok: boolean; message: string }>

const signInInstance: SignInSubmit = (target, token, screen, remember) =>
  api.loginInstance(target.url, target.tenant, token, screen, remember)

export const signInKey = (t: SignInTarget) => `${t.host}|${(t.tenant ?? '').toLowerCase()}`

type Phase = 'intro' | 'waiting' | 'done' | 'error'

const LIMIT_MINUTES = 5
const REMEMBER_DAYS = 30
const REMEMBER_KEY = 'ov-agent.signin-remember'
const CLOSE_AFTER_SUCCESS_MS = 1400
const SECONDS_PER_MINUTE = MINUTE_MS / SECOND_MS

const REMEMBER_INFO = `After you sign in, ov creates an API token in your name that lasts ${REMEMBER_DAYS} days and keeps it instead of the short web session, so you are not asked again until it expires. You can see it in Admin > Auth Tokens. Turn this off to keep only the web session.`

function RememberInfo() {
  const [open, setOpen] = useState(false)

  return (
    <span
      className="relative flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label="How staying signed in works"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="text-faint hover:text-muted flex size-5 items-center justify-center rounded-full"
      >
        <InfoIcon className="size-3.5" />
      </button>
      {open ? (
        <span
          role="tooltip"
          className="animate-tip border-line-strong/70 text-text absolute bottom-full left-1/2 z-10 mb-1.5 -ml-28 w-56 rounded-xl border bg-white px-3 py-2 text-[11.5px] leading-relaxed shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
        >
          {REMEMBER_INFO}
        </span>
      ) : null}
    </span>
  )
}

function Step({ n, children }: { n: number; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="bg-brand-soft text-brand-strong mt-px flex size-6 shrink-0 items-center justify-center rounded-full text-[11.5px] font-semibold">
        {n}
      </span>
      <span className="text-text pt-0.5 text-[13px] leading-relaxed">{children}</span>
    </li>
  )
}

const ANOTHER_SIGN_IN = /another sign-in is still/
const DEFAULT_FIX =
  'Check that the address is right and that you can sign in to it in a normal browser.'

const FIXES: {
  pattern: RegExp
  method?: SignInMethod
  tip: (tenant?: string) => string | undefined
}[] = [
  {
    pattern: /tenant|not allowed|no tenant/,
    tip: (tenant) =>
      tenant &&
      `${tenant} needs a user with your email address. Ask an admin of that tenant to add one, or sign in without a tenant.`,
  },
  {
    pattern: /not accepted|401|unauthori|rejected/,
    method: 'token',
    tip: () => 'Check both keys in Admin > Auth Tokens, and that the token is still active.',
  },
  {
    pattern: /failed while issuing an api token/,
    tip: () =>
      'The instance hit an error of its own. Its server log shows why; an API token works meanwhile.',
  },
  {
    pattern: /may not create api tokens/,
    tip: () =>
      `Turn off "Stay signed in for ${REMEMBER_DAYS} days" to sign in with a session token instead.`,
  },
  {
    pattern: /widget module/,
    tip: () => 'Your account needs the Widget module at Read; the token request depends on it.',
  },
  {
    pattern: /timed out|timeout|took too long/,
    tip: () =>
      `The browser window waited ${LIMIT_MINUTES} minutes. Start again and finish signing in sooner.`,
  },
  {
    pattern: /browser|playwright|chromium/,
    tip: () => 'The sign-in browser may be missing. Run "ov setup" in a terminal, then try again.',
  },
]

function likelyFixes(message: string, method: SignInMethod, tenant?: string): string[] {
  const text = message.toLowerCase()
  if (ANOTHER_SIGN_IN.test(text)) return []

  const tips = FIXES.filter((f) => (f.method ?? method) === method && f.pattern.test(text))
    .map((f) => f.tip(tenant))
    .filter((tip): tip is string => Boolean(tip))
  return tips.length ? tips : [DEFAULT_FIX]
}

export function SignInModal({
  target,
  pending,
  onClose,
  onStart,
  onFinished,
  submit = signInInstance,
}: {
  target?: SignInTarget
  pending: boolean
  onClose: () => void
  onStart: (target: SignInTarget) => void
  onFinished: (target: SignInTarget, ok: boolean) => void
  submit?: SignInSubmit
}) {
  const [phase, setPhase] = useState<Phase>('intro')
  const [message, setMessage] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [method, setMethod] = useState<SignInMethod>('browser')
  const [separate, setSeparate] = useState(false)
  const [accessKey, setAccessKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [remember, setRemember] = useState(() => localStorage.getItem(REMEMBER_KEY) !== 'false')
  const startedAt = useRef(0)
  const current = useRef(target)
  current.current = target
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const targetKey = target && signInKey(target)
  const shown = useEnterTransition(targetKey)
  const stillShowing = (t: SignInTarget) =>
    current.current !== undefined && signInKey(current.current) === signInKey(t)

  useEffect(() => {
    if (!target) return

    setPhase(pending ? 'waiting' : 'intro')
    setMessage('')
    setMethod(target.tenant ? 'browser' : (target.mode ?? 'browser'))
    setSeparate(false)
    setAccessKey('')
    setSecretKey('')
  }, [targetKey])

  useEffect(() => {
    if (phase !== 'waiting') return

    if (!startedAt.current) startedAt.current = Date.now()
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - startedAt.current) / SECOND_MS)),
      SECOND_MS,
    )
    return () => clearInterval(timer)
  }, [phase])

  useEffect(() => () => clearTimeout(closeTimer.current), [])

  const streaming = phase === 'waiting' && method === 'browser' && !separate
  const dismiss = () => {
    if (streaming && target) void api.cancelSignIn(target.url, target.tenant).catch(reportError)
    onClose()
  }

  useLayer(dismiss, Boolean(target))

  if (!target) return null

  const { host, tenant } = target
  const byToken = method === 'token'
  const ready = !byToken || (accessKey.trim() && secretKey.trim())

  const start = async (inWindow = false) => {
    const t = target
    startedAt.current = Date.now()
    setElapsed(0)
    setSeparate(inWindow)
    setPhase('waiting')
    onStart(t)

    const res = await submit(
      t,
      byToken ? `${accessKey.trim()}:${secretKey.trim()}` : undefined,
      byToken || inWindow ? undefined : screenSize(),
      !byToken && remember,
    ).catch((e: Error) => ({ ok: false, message: e.message }))

    onFinished(t, res.ok)
    startedAt.current = 0

    if (!stillShowing(t)) return

    if (res.ok) {
      setPhase('done')
      closeTimer.current = setTimeout(() => {
        if (stillShowing(t)) onClose()
      }, CLOSE_AFTER_SUCCESS_MS)
    } else {
      setMessage(res.message || 'Sign-in failed.')
      setPhase('error')
    }
  }

  const clock = `${Math.floor(elapsed / SECONDS_PER_MINUTE)}:${String(elapsed % SECONDS_PER_MINUTE).padStart(2, '0')}`
  const embedded = phase === 'waiting' && !byToken && !separate

  if (embedded) {
    const size = screenSize()

    return createPortal(
      <div
        className={cn(
          'fixed inset-0 z-[100] flex items-center justify-center bg-[#263238]/30 backdrop-blur-[2px] transition-opacity duration-200',
          shown ? 'opacity-100' : 'opacity-0',
        )}
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Sign in to ${host}`}
          className="animate-pop overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.3)]"
          style={{ width: size.width, height: size.height + SCREEN_BAR_PX }}
        >
          <LiveScreen
            streamUrl={api.signInScreenUrl(target.url, tenant)}
            send={(events) => api.signInInput(target.url, tenant, events)}
            address={target.url}
            label={`Sign-in page for ${host}`}
            starting={`Opening ${host}`}
            closeLabel="Cancel sign-in"
            onClose={dismiss}
            status={
              <span className="bg-brand-soft text-brand-strong busy-sweep hidden h-8 shrink-0 items-center gap-2 rounded-full px-3 text-[12px] font-medium sm:inline-flex">
                {tenant ? `Tenant ${tenant}` : 'Sign in'}
                <span className="text-brand-strong/60 tabular-nums">{clock}</span>
              </span>
            }
          />
        </div>
      </div>,
      document.body,
    )
  }

  return createPortal(
    <div
      className={cn(
        'fixed inset-0 z-[100] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px] transition-opacity duration-200',
        shown ? 'opacity-100' : 'opacity-0',
      )}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Sign in to ${host}`}
        className={cn(
          'modal-enter w-full max-w-[480px] rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)]',
          shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-3 scale-[0.98] opacity-0',
        )}
      >
        <div className="flex items-start gap-3.5 px-5 pt-5">
          <span
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-full',
              phase === 'done'
                ? 'bg-ok-soft text-ok'
                : phase === 'error'
                  ? 'bg-danger-soft text-danger'
                  : 'bg-brand-soft text-brand-strong',
            )}
          >
            {phase === 'done' ? <CheckIcon className="size-5" /> : <KeyIcon className="size-5" />}
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">
              {phase === 'done'
                ? 'Signed in'
                : phase === 'error'
                  ? 'Sign-in did not finish'
                  : 'Sign in to OneVizion'}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span className="bg-raised text-text inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium">
                <GlobeAltIcon className="text-muted size-3" />
                {host}
              </span>
              {tenant ? (
                <span className="bg-brand-soft text-brand-strong inline-flex h-6 items-center rounded-full px-2.5 text-[12px] font-medium">
                  Tenant {tenant}
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            aria-label={phase === 'waiting' ? 'Hide' : 'Close'}
            onClick={onClose}
            className="text-faint hover:text-fg hover:bg-raised -mt-1 -mr-1 flex size-8 items-center justify-center rounded-full transition-colors"
          >
            <XMarkIcon className="size-4" />
          </button>
        </div>

        {phase === 'intro' && !tenant ? (
          <div className="bg-raised mx-5 mt-5 flex rounded-full p-1">
            {(['browser', 'token'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMethod(m)}
                className={cn(
                  'h-8 flex-1 rounded-full text-[12.5px] font-medium transition-colors',
                  m === method ? 'text-fg bg-white shadow-sm' : 'text-muted hover:text-fg',
                )}
              >
                {m === 'browser' ? 'Browser' : 'API token'}
              </button>
            ))}
          </div>
        ) : null}

        {byToken && (phase === 'intro' || phase === 'waiting') ? (
          <div className="mt-4 space-y-3 px-5">
            <Input
              value={accessKey}
              onChange={(e) => setAccessKey(e.target.value)}
              placeholder="Access key"
              aria-label="Access key"
              autoComplete="off"
              spellCheck={false}
              disabled={phase === 'waiting'}
            />
            <Input
              type="password"
              value={secretKey}
              onChange={(e) => setSecretKey(e.target.value)}
              placeholder="Secret key"
              aria-label="Secret key"
              autoComplete="off"
              disabled={phase === 'waiting'}
            />
            <div className="bg-raised text-muted flex gap-2.5 rounded-2xl px-3.5 py-3 text-[12px] leading-relaxed">
              <LockClosedIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>
                Create one in Admin &gt; Auth Tokens on {host}. It works with that user's privileges
                and tenant, and is kept encrypted on this computer.
              </span>
            </div>
          </div>
        ) : null}

        {!byToken && (phase === 'intro' || phase === 'waiting') ? (
          <>
            <ol className="mt-5 space-y-3 px-5">
              <Step n={1}>
                <b className="text-fg font-medium">{host}</b>'s own login page opens right here.
              </Step>
              <Step n={2}>Sign in the way you always do. Single sign-on and MFA are fine.</Step>
              {tenant ? (
                <Step n={3}>
                  You land in your own tenant first; that is expected. Do not switch tenants in the
                  browser: once you are in, ov switches to{' '}
                  <b className="text-fg font-medium">{tenant}</b> for you.
                </Step>
              ) : null}
              <Step n={tenant ? 4 : 3}>It closes on its own when you are through.</Step>
            </ol>
            <div className="bg-raised text-muted mx-5 mt-4 flex gap-2.5 rounded-2xl px-3.5 py-3 text-[12px] leading-relaxed">
              <LockClosedIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>
                Your password only goes into the instance's own page, and ov works with your
                privileges.
                {tenant
                  ? ` Switching needs a user with your email address in ${tenant}.`
                  : ' For another tenant on this host, add it with a tenant name.'}
              </span>
            </div>
            {phase === 'intro' ? (
              <div className="mx-5 mt-3 flex items-center gap-1.5 px-3.5 text-[12.5px]">
                <span className="text-text">Stay signed in for {REMEMBER_DAYS} days</span>
                <RememberInfo />
                <span className="flex-1" />
                <button
                  type="button"
                  role="switch"
                  aria-checked={remember}
                  aria-label={`Stay signed in for ${REMEMBER_DAYS} days`}
                  onClick={() => {
                    localStorage.setItem(REMEMBER_KEY, String(!remember))
                    setRemember(!remember)
                  }}
                  className={cn(SWITCH_TRACK, remember ? 'bg-brand' : 'bg-line-strong')}
                >
                  <SwitchKnob on={remember} />
                </button>
              </div>
            ) : null}
          </>
        ) : null}

        {phase === 'done' ? (
          <div className="text-muted px-5 pt-4 text-[13px]">
            {tenant ? `${host} tenant ${tenant}` : host} is ready to use.
          </div>
        ) : null}

        {phase === 'error' ? (
          <div className="mt-4 space-y-3 px-5">
            <div className="border-danger/25 bg-danger-soft/50 text-text max-h-[140px] scrollbar-thin overflow-y-auto rounded-2xl border px-3.5 py-2.5 text-[12px] leading-relaxed break-words whitespace-pre-wrap">
              {message}
            </div>
            <ul className="space-y-1.5">
              {likelyFixes(message, method, tenant).map((tip) => (
                <li key={tip} className="text-muted flex gap-2 text-[12.5px] leading-relaxed">
                  <span className="bg-brand mt-2 size-1.5 shrink-0 rounded-full" />
                  {tip}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2 px-5 pb-5">
          {phase === 'intro' ? (
            <>
              {byToken ? null : (
                <button
                  type="button"
                  onClick={() => void start(true)}
                  className="text-muted hover:text-brand-strong mr-auto text-[12px] transition-colors"
                >
                  Use a separate window
                </button>
              )}
              <Button variant="ghost" size="lg" onClick={onClose}>
                Cancel
              </Button>
              <Button variant="primary" size="lg" disabled={!ready} onClick={() => void start()}>
                <KeyIcon className="size-4" /> {byToken ? 'Sign in' : 'Open sign-in page'}
              </Button>
            </>
          ) : phase === 'waiting' ? (
            <>
              <span className="bg-brand-soft text-brand-strong busy-sweep mr-auto inline-flex h-10 items-center gap-2 rounded-full px-4 text-[12.5px] font-medium">
                {byToken ? (
                  'Checking the token'
                ) : (
                  <>
                    Waiting for you in the browser
                    <span className="text-brand-strong/60 tabular-nums">
                      {clock} / {LIMIT_MINUTES}:00
                    </span>
                  </>
                )}
              </span>
              <Button variant="ghost" size="lg" onClick={onClose}>
                Hide
              </Button>
            </>
          ) : phase === 'done' ? (
            <Button variant="primary" size="lg" onClick={onClose}>
              Done
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="lg" onClick={onClose}>
                Close
              </Button>
              <Button
                variant="primary"
                size="lg"
                onClick={() => (byToken ? setPhase('intro') : void start())}
              >
                <ArrowPathIcon className="size-4" /> Try again
              </Button>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function AddInstanceForm({
  onSubmit,
  className,
}: {
  onSubmit: (target: SignInTarget) => void
  className?: string
}) {
  const [url, setUrl] = useState('')
  const [tenant, setTenant] = useState('')

  return (
    <form
      className={cn('flex flex-wrap gap-2', className)}
      onSubmit={(e) => {
        e.preventDefault()
        if (!url.trim()) return
        onSubmit({ url: url.trim(), host: hostOf(url), tenant: tenant.trim() || undefined })
        setUrl('')
        setTenant('')
      }}
    >
      <Input
        className="min-w-[220px] flex-[2]"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Instance address, e.g. acme.onevizion.com"
        aria-label="Instance address"
      />
      <Input
        className="min-w-[150px] flex-1"
        value={tenant}
        onChange={(e) => setTenant(e.target.value)}
        placeholder="Tenant (optional)"
        aria-label="Tenant"
      />
      <Button type="submit" variant="primary" disabled={!url.trim()}>
        Sign in
      </Button>
    </form>
  )
}
