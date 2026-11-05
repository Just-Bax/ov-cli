import { ArrowSquareOut as ArrowTopRightOnSquareIcon, Key as KeyIcon } from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import type { Instance } from '@shared/types.ts'
import { Button } from '@/components/common/ui'
import { SignInModal, type SignInTarget } from '@/components/signin/SignInModal'
import { cn } from '@/lib/cn'
import { useClickOutside } from '@/lib/hooks'
import { useInstances } from '@/lib/instances'
import { hostOf } from '@/lib/url'

type State = 'loading' | 'missing' | 'ok' | 'expired'
type Used = { key: string; host: string; url: string; found?: Instance; state: State }

const STATE_DOT: Record<State, string> = {
  ok: 'bg-ok',
  loading: 'bg-line-strong',
  missing: 'bg-warn',
  expired: 'bg-warn',
}

const STATE_TEXT: Record<State, string> = {
  ok: 'Signed in',
  loading: 'Loading',
  missing: 'Not signed in',
  expired: 'Session expired',
}

function resolve(instance: string, known: Instance[] | undefined): Instance | undefined {
  return known?.find((i) => i.alias === instance) ?? known?.find((i) => i.host === hostOf(instance))
}

function used(instances: string[], known: Instance[] | undefined): Used[] {
  const rows = [...instances].reverse().map((instance) => {
    const found = resolve(instance, known)
    const host = found?.host ?? hostOf(instance)
    const state: State = !known ? 'loading' : !found ? 'missing' : found.valid ? 'ok' : 'expired'
    return { key: found?.alias ?? host, host, url: found?.url ?? `https://${host}`, found, state }
  })
  return rows.filter((row, index) => rows.findIndex((r) => r.key === row.key) === index)
}

function overall(rows: Used[]): State {
  if (rows.some((r) => r.state === 'loading')) return 'loading'
  return rows.find((r) => r.state !== 'ok')?.state ?? 'ok'
}

export function InstanceChips({ instances }: { instances: string[] }) {
  const { instances: known, reload } = useInstances()
  const [open, setOpen] = useState(false)
  const [signIn, setSignIn] = useState<SignInTarget>()
  const box = useRef<HTMLSpanElement>(null)
  const rows = used(instances, known)
  const [latest] = rows
  const several = rows.length > 1

  useClickOutside([box], () => setOpen(false), open)

  if (!latest) return null

  return (
    <span ref={box} className="relative min-w-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title={several ? `${rows.length} instances used in this thread` : 'Instance details'}
        className="hover:text-brand-strong inline-flex max-w-full items-center gap-1.5 whitespace-nowrap"
      >
        <span className={cn('size-1.5 shrink-0 rounded-full', STATE_DOT[overall(rows)])} />
        {latest.host}
        {latest.found?.tenant ? <span className="text-faint">/ {latest.found.tenant}</span> : null}
        {several ? (
          <span className="bg-raised text-muted rounded-full px-1.5 text-[11px] font-medium tabular-nums">
            +{rows.length - 1}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="border-line animate-pop absolute top-full left-0 z-40 mt-2 w-[360px] max-w-[calc(100vw-32px)] rounded-2xl border bg-white p-1.5 text-[12.5px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]">
          {several ? (
            <div className="text-muted px-2.5 pt-1.5 pb-1 text-[11.5px] font-medium">
              {rows.length} instances in this thread
            </div>
          ) : null}
          {rows.map((row, index) => (
            <div key={row.key} className="flex items-start gap-2.5 rounded-xl px-2.5 py-2">
              <span className={cn('mt-[5px] size-2 shrink-0 rounded-full', STATE_DOT[row.state])} />
              <div className="min-w-0 flex-1">
                <div className="text-fg font-medium break-all">{row.host}</div>
                <div className="text-muted mt-0.5 text-[11.5px]">
                  {STATE_TEXT[row.state]}
                  {row.found?.tenant ? `, tenant ${row.found.tenant}` : ''}
                  {several && index === 0 ? ', used last' : ''}
                </div>
              </div>
              {row.state === 'expired' || row.state === 'missing' ? (
                <Button
                  size="sm"
                  variant="primary"
                  className="shrink-0 gap-1.5"
                  onClick={() =>
                    setSignIn({ url: row.url, host: row.host, tenant: row.found?.tenant })
                  }
                >
                  <KeyIcon className="size-3.5" /> Sign in
                </Button>
              ) : null}
              <a
                href={row.url}
                target="_blank"
                rel="noreferrer"
                title="Open in a new tab"
                className="text-muted hover:text-brand-strong hover:bg-raised -mt-1 flex size-7 shrink-0 items-center justify-center rounded-full"
              >
                <ArrowTopRightOnSquareIcon className="size-4" />
              </a>
            </div>
          ))}
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
