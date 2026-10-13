import {
  ArrowsClockwise as ArrowPathIcon,
  Check as CheckIcon,
  Globe as GlobeAltIcon,
  Key as KeyIcon,
  Lock as LockClosedIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RemoteScreen, SCREEN_BAR_PX, screenSize } from '@/components/RemoteScreen'
import { Button, Input, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useLayer } from '@/lib/layers'
import { cn } from '@/lib/cn'
import { reportError } from '@/components/Toasts'

export type SignInMethod = 'browser' | 'token'

export type SignInTarget = { url: string; host: string; tenant?: string; mode?: SignInMethod }

export type SignInSubmit = (
  target: SignInTarget,
  token?: string,
  screen?: { width: number; height: number },
) => Promise<{ ok: boolean; message: string }>

const signInInstance: SignInSubmit = (target, token, screen) =>
  api.loginInstance(target.url, target.tenant, token, screen)

export const signInKey = (t: SignInTarget) => `${t.host}|${(t.tenant ?? '').toLowerCase()}`

function hostOf(value: string): string {
  return value
    .trim()
    .replace(/^[a-z]+:\/\//i, '')
    .split(/[/?#]/)[0]
    .toLowerCase()
}

type Phase = 'intro' | 'waiting' | 'done' | 'error'

const LIMIT_SECONDS = 300
const CLOCK_TICK_MS = 1000
const CLOSE_AFTER_SUCCESS_MS = 1400

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

function likelyFixes(message: string, tenant?: string): string[] {
  const text = message.toLowerCase()
  const out: string[] = []
  if (/another sign-in is still/.test(text)) return []
  if (tenant && /tenant|not allowed|no tenant/.test(text))
    out.push(
      `${tenant} needs a user with your email address. Ask an admin of that tenant to add one, or sign in without a tenant.`,
    )
  if (/accesskey|auth tokens|not accepted|401|unauthori/.test(text))
    out.push('Check both keys in Admin > Auth Tokens, and that the token is still active.')
  if (/widget|token endpoint|refus/.test(text))
    out.push('Your account needs the Widget module at Read; the token request depends on it.')
  if (/timed out|timeout|took too long/.test(text))
    out.push('The browser window waited 5 minutes. Start again and finish signing in sooner.')
  if (/browser|playwright|chromium/.test(text))
    out.push('The sign-in browser may be missing. Run "ov setup" in a terminal, then try again.')
  if (!out.length)
    out.push('Check that the address is right and that you can sign in to it in a normal browser.')

  return out
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
  const [shown, setShown] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [method, setMethod] = useState<SignInMethod>('browser')
  const [separate, setSeparate] = useState(false)
  const [accessKey, setAccessKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const startedAt = useRef(0)
  const current = useRef(target)
  current.current = target
  const targetKey = target && signInKey(target)
  const stillShowing = (t: SignInTarget) =>
    current.current !== undefined && signInKey(current.current) === signInKey(t)

  useEffect(() => {
    if (!target) {
      setShown(false)
      return
    }

    setPhase(pending ? 'waiting' : 'intro')
    setMessage('')
    setMethod(target.tenant ? 'browser' : (target.mode ?? 'browser'))
    setSeparate(false)
    setAccessKey('')
    setSecretKey('')
    const frame = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(frame)
  }, [targetKey])

  useEffect(() => {
    if (phase !== 'waiting') return

    if (!startedAt.current) startedAt.current = Date.now()
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)),
      CLOCK_TICK_MS,
    )
    return () => clearInterval(timer)
  }, [phase])

  useLayer(onClose, Boolean(target))

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
    ).catch((e: Error) => ({ ok: false, message: e.message }))
    onFinished(t, res.ok)
    startedAt.current = 0
    if (!stillShowing(t)) return

    if (res.ok) {
      setPhase('done')
      setTimeout(() => {
        if (stillShowing(t)) onClose()
      }, CLOSE_AFTER_SUCCESS_MS)
    } else {
      setMessage(res.message || 'Sign-in failed.')
      setPhase('error')
    }
  }

  const clock = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`
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
          style={{ width: size.width, maxHeight: size.height + SCREEN_BAR_PX }}
        >
          <RemoteScreen
            url={target.url}
            host={host}
            tenant={tenant}
            onCancel={() => {
              void api.cancelSignIn(target.url, tenant).catch(reportError)
              onClose()
            }}
            status={
              <span className="bg-brand-soft text-brand-strong hidden h-8 shrink-0 items-center gap-2 rounded-full px-3 text-[12px] font-medium sm:inline-flex">
                <Spinner className="size-3" />
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
          'ease-spring w-full max-w-[480px] rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)] transition-[transform,opacity] duration-300',
          shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-6 scale-[0.97] opacity-0',
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
                Your password only goes into the instance's own page. ov keeps just a session token,
                with your privileges.
                {tenant
                  ? ` Switching needs a user with your email address in ${tenant}.`
                  : ' For another tenant on this host, add it with a tenant name.'}
              </span>
            </div>
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
              {likelyFixes(message, tenant).map((tip) => (
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
              <span className="bg-brand-soft text-brand-strong mr-auto inline-flex h-10 items-center gap-2 rounded-full px-4 text-[12.5px] font-medium">
                <Spinner className="size-3.5" />
                {byToken ? (
                  'Checking the token'
                ) : (
                  <>
                    Waiting for you in the browser
                    <span className="text-brand-strong/60 tabular-nums">
                      {clock} / {LIMIT_SECONDS / 60}:00
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
