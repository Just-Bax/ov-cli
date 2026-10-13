import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  ArrowsClockwise as ArrowPathIcon,
  Key as KeyIcon,
} from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import { reportError } from '@/components/common/Toasts'
import { Button, Spinner } from '@/components/common/ui'
import { SignInModal, type SignInTarget } from '@/components/signin/SignInModal'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useClickOutside } from '@/lib/hooks'
import { useInstances } from '@/lib/instances'
import { hostOf } from '@/lib/url'

type Check = { version: string | null; ms: number }
type State = 'loading' | 'missing' | 'ok' | 'expired'

const STATE_DOT: Record<State, string> = {
  ok: 'bg-ok',
  loading: 'bg-line-strong',
  missing: 'bg-warn',
  expired: 'bg-warn',
}

export function InstanceChip({ instance }: { instance: string }) {
  const { instances: known, reload } = useInstances()
  const [open, setOpen] = useState(false)
  const [check, setCheck] = useState<Check>()
  const [checking, setChecking] = useState(false)
  const [signIn, setSignIn] = useState<SignInTarget>()
  const box = useRef<HTMLSpanElement>(null)

  useClickOutside([box], () => setOpen(false), open)

  const found =
    known?.find((i) => i.alias === instance) ?? known?.find((i) => i.host === hostOf(instance))
  const host = found?.host ?? hostOf(instance)
  const state: State = !known ? 'loading' : !found ? 'missing' : found.valid ? 'ok' : 'expired'
  const url = found?.url ?? `https://${host}`

  const runCheck = () => {
    setChecking(true)
    api
      .checkInstance(found?.alias ?? host)
      .then(setCheck, reportError)
      .finally(() => setChecking(false))
  }

  return (
    <span ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Instance details"
        className="hover:text-brand-strong inline-flex items-center gap-1.5"
      >
        <span className={cn('size-1.5 rounded-full', STATE_DOT[state])} />
        {host}
        {found?.tenant ? <span className="text-faint">/ {found.tenant}</span> : null}
      </button>
      {open ? (
        <div className="border-line animate-pop absolute top-full left-0 z-40 mt-2 w-[280px] rounded-2xl border bg-white p-3 text-[12.5px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]">
          <div className="flex items-center gap-2">
            <span className={cn('size-2 shrink-0 rounded-full', STATE_DOT[state])} />
            <span className="text-fg min-w-0 flex-1 truncate font-semibold">{host}</span>
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              title="Open in OneVizion"
              className="text-muted hover:text-brand-strong hover:bg-raised flex size-7 items-center justify-center rounded-full"
            >
              <ArrowTopRightOnSquareIcon className="size-4" />
            </a>
          </div>
          <div className="text-muted mt-1 pl-4">
            {state === 'ok'
              ? `Signed in${found?.tenant ? `, tenant ${found.tenant}` : ''}`
              : state === 'expired'
                ? 'Session expired'
                : state === 'missing'
                  ? 'Not signed in'
                  : 'Loading'}
          </div>
          <button
            type="button"
            disabled={checking}
            onClick={runCheck}
            className="text-muted hover:bg-raised hover:text-fg mt-2 flex h-8 w-full items-center gap-2 rounded-xl px-2 text-left"
          >
            {checking ? <Spinner className="size-3.5" /> : <ArrowPathIcon className="size-3.5" />}
            <span className="flex-1">
              {check
                ? `Version ${check.version ?? 'unknown'}, ${check.ms} ms`
                : 'Check version and response time'}
            </span>
          </button>
          {state === 'expired' || state === 'missing' ? (
            <Button
              variant="primary"
              className="mt-2 w-full"
              onClick={() => setSignIn({ url, host, tenant: found?.tenant })}
            >
              <KeyIcon className="size-4" /> Sign in
            </Button>
          ) : null}
        </div>
      ) : null}
      <SignInModal
        target={signIn}
        pending={false}
        onClose={() => setSignIn(undefined)}
        onStart={() => undefined}
        onFinished={() => void reload()}
      />
    </span>
  )
}
