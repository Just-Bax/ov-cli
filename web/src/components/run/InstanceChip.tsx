import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  ArrowsClockwise as ArrowPathIcon,
  Key as KeyIcon,
} from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import type { Instance } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button } from '@/components/common/ui'
import { SignInModal, type SignInTarget } from '@/components/signin/SignInModal'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useClickOutside } from '@/lib/hooks'
import { useInstances } from '@/lib/instances'
import { hostOf } from '@/lib/url'

type Check = { version: string | null; ms: number }
type State = 'loading' | 'missing' | 'ok' | 'expired'

const MAX_SHOWN = 3

const STATE_DOT: Record<State, string> = {
  ok: 'bg-ok',
  loading: 'bg-line-strong',
  missing: 'bg-warn',
  expired: 'bg-warn',
}

function resolve(instance: string, known: Instance[] | undefined): Instance | undefined {
  return known?.find((i) => i.alias === instance) ?? known?.find((i) => i.host === hostOf(instance))
}

export function InstanceChips({ instances }: { instances: string[] }) {
  const { instances: known, reload } = useInstances()
  const byRecent = [...instances].reverse()
  const keyOf = (instance: string) => resolve(instance, known)?.alias ?? hostOf(instance)
  const distinct = byRecent.filter(
    (i, index) => byRecent.findIndex((j) => keyOf(j) === keyOf(i)) === index,
  )
  const shown = distinct.slice(0, MAX_SHOWN)
  const hidden = distinct.slice(MAX_SHOWN)

  return (
    <span className="inline-flex min-w-0 items-center gap-3">
      {shown.map((instance, index) => (
        <InstanceChip
          key={keyOf(instance)}
          instance={instance}
          found={resolve(instance, known)}
          loading={!known}
          latest={index === 0 && distinct.length > 1}
          reload={reload}
        />
      ))}
      {hidden.length ? (
        <span className="text-faint" title={hidden.map(hostOf).join(', ')}>
          +{hidden.length}
        </span>
      ) : null}
    </span>
  )
}

function InstanceChip({
  instance,
  found,
  loading,
  latest,
  reload,
}: {
  instance: string
  found: Instance | undefined
  loading: boolean
  latest: boolean
  reload: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [check, setCheck] = useState<Check>()
  const [checking, setChecking] = useState(false)
  const [signIn, setSignIn] = useState<SignInTarget>()
  const box = useRef<HTMLSpanElement>(null)

  useClickOutside([box], () => setOpen(false), open)

  const host = found?.host ?? hostOf(instance)
  const state: State = loading ? 'loading' : !found ? 'missing' : found.valid ? 'ok' : 'expired'
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
        title={latest ? 'Used last in this thread' : 'Instance details'}
        className="hover:text-brand-strong inline-flex items-center gap-1.5 whitespace-nowrap"
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
            className={cn(
              'text-muted hover:bg-raised hover:text-fg mt-2 flex h-8 w-full items-center gap-2 rounded-xl px-2 text-left',
              checking && 'busy-sweep',
            )}
          >
            <ArrowPathIcon className="size-3.5" />
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
