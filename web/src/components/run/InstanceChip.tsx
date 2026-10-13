import {
  ArrowPathIcon,
  ArrowTopRightOnSquareIcon,
  GlobeAltIcon,
  HeartIcon,
  KeyIcon,
} from '@heroicons/react/24/outline'
import { useEffect, useRef, useState } from 'react'
import type { Instance } from '@shared/types.ts'
import { SignInModal, type SignInTarget } from '@/components/SignInModal'
import { reportError } from '@/components/Toasts'
import { Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { href } from '@/lib/route'

type Check = { version: string | null; ms: number }

function hostOf(value: string): string {
  return value
    .replace(/^[a-z]+:\/\//i, '')
    .split(/[/?#]/)[0]
    .toLowerCase()
}

export function InstanceChip({ instance }: { instance: string }) {
  const [known, setKnown] = useState<Instance[]>()
  const [open, setOpen] = useState(false)
  const [check, setCheck] = useState<Check>()
  const [checking, setChecking] = useState(false)
  const [signIn, setSignIn] = useState<SignInTarget>()
  const box = useRef<HTMLSpanElement>(null)

  const load = () => api.instances().then(setKnown, reportError)
  useEffect(() => void load(), [])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const found =
    known?.find((i) => i.alias === instance) ?? known?.find((i) => i.host === hostOf(instance))
  const host = found?.host ?? hostOf(instance)
  const state = !known ? 'loading' : !found ? 'missing' : found.valid ? 'ok' : 'expired'
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
        <span
          className={cn(
            'size-1.5 rounded-full',
            state === 'ok' ? 'bg-ok' : state === 'loading' ? 'bg-line-strong' : 'bg-warn',
          )}
        />
        {found?.alias ?? instance}
        {found?.tenant ? <span className="text-faint">/ {found.tenant}</span> : null}
      </button>
      {open ? (
        <div className="border-line animate-pop absolute top-full left-0 z-40 mt-2 w-[300px] rounded-2xl border bg-white p-3.5 text-[12.5px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]">
          <div className="text-fg flex items-center gap-2 font-semibold">
            <GlobeAltIcon className="text-muted size-4" />
            <span className="truncate">{host}</span>
          </div>
          <div className="text-muted mt-1">
            {state === 'ok'
              ? `Signed in${found?.mode === 'token' ? ' with an API token' : ''}${found?.expires ? `, until ${found.expires}` : ''}.`
              : state === 'expired'
                ? 'The session has expired. The agent asks you to sign in when it needs it.'
                : state === 'missing'
                  ? 'Not signed in on this computer.'
                  : 'Loading...'}
          </div>
          {check ? (
            <div className="bg-raised text-text mt-2.5 rounded-xl px-3 py-2">
              Version <b className="text-fg font-medium">{check.version ?? 'unknown'}</b>, answered
              in {check.ms} ms
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="bg-raised text-text hover:bg-brand-soft hover:text-brand-strong inline-flex h-8 items-center gap-1.5 rounded-full px-3 font-medium"
            >
              <ArrowTopRightOnSquareIcon className="size-3.5" /> Open
            </a>
            <button
              type="button"
              disabled={checking}
              onClick={runCheck}
              className="bg-raised text-text hover:bg-brand-soft hover:text-brand-strong inline-flex h-8 items-center gap-1.5 rounded-full px-3 font-medium"
            >
              {checking ? <Spinner className="size-3.5" /> : <ArrowPathIcon className="size-3.5" />}
              Check
            </button>
            <a
              href={href({ page: 'health' })}
              className="bg-raised text-text hover:bg-brand-soft hover:text-brand-strong inline-flex h-8 items-center gap-1.5 rounded-full px-3 font-medium"
            >
              <HeartIcon className="size-3.5" /> Health
            </a>
            {state === 'expired' || state === 'missing' ? (
              <button
                type="button"
                onClick={() => setSignIn({ url, host, tenant: found?.tenant })}
                className="bg-brand text-on-brand hover:bg-brand-strong inline-flex h-8 items-center gap-1.5 rounded-full px-3 font-medium"
              >
                <KeyIcon className="size-3.5" /> Sign in
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      <SignInModal
        target={signIn}
        pending={false}
        onClose={() => setSignIn(undefined)}
        onStart={() => undefined}
        onFinished={() => void load()}
      />
    </span>
  )
}
