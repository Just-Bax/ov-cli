import { CircleAlert, CircleCheck, CircleSlash, Plus, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { RunStatus, RunSummary } from '@shared/types.ts'
import { Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { href, type Route } from '@/lib/route'

export function StatusIcon({ status, className }: { status: RunStatus; className?: string }) {
  if (status === 'running' || status === 'queued')
    return <Spinner className={cn('text-brand size-3.5', className)} />
  if (status === 'waiting')
    return <span className={cn('bg-warn block size-2 rounded-full', className)} />
  if (status === 'done') return <CircleCheck className={cn('text-ok size-3.5', className)} />
  if (status === 'cancelled')
    return <CircleSlash className={cn('text-faint size-3.5', className)} />
  return <CircleAlert className={cn('text-danger size-3.5', className)} />
}

function group(runs: RunSummary[]): [string, RunSummary[]][] {
  const startOfDay = new Date().setHours(0, 0, 0, 0)
  const buckets: [string, RunSummary[]][] = [
    ['Working', []],
    ['Today', []],
    ['Earlier', []],
  ]
  for (const r of runs) {
    if (['queued', 'running', 'waiting'].includes(r.status)) buckets[0][1].push(r)
    else if (r.createdAt >= startOfDay) buckets[1][1].push(r)
    else buckets[2][1].push(r)
  }
  return buckets.filter(([, list]) => list.length)
}

export function Sidebar({ route, user }: { route: Route; user?: string }) {
  const [runs, setRuns] = useState<RunSummary[]>()

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .runs()
        .then((r) => alive && setRuns(r))
        .catch(() => undefined)
    load()
    const t = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const item = (active: boolean) =>
    cn(
      'flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] transition-colors',
      active ? 'bg-black/[0.06] text-fg font-medium' : 'text-text hover:bg-black/[0.04]',
    )

  return (
    <aside className="bg-canvas border-line-strong/40 flex w-[260px] shrink-0 flex-col border-r">
      <div className="flex h-16 items-center px-4">
        <a href="#/" className="text-fg text-[15px] font-semibold">
          OV Agent
        </a>
      </div>
      <nav className="space-y-0.5 px-2">
        <a href="#/" className={item(route.page === 'home')}>
          <Plus className="size-4" /> New run
        </a>
      </nav>

      <div className="mt-4 min-h-0 flex-1 scrollbar-thin overflow-y-auto px-2 pb-2">
        {!runs ? (
          <div className="space-y-3 px-2.5 pt-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} dim className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
            ))}
          </div>
        ) : null}
        {group(runs ?? []).map(([label, list]) => (
          <div key={label} className="mb-3">
            <div className="text-faint px-2.5 pb-1 text-[11.5px] font-medium">{label}</div>
            {list.map((r) => {
              const active = route.page === 'run' && route.id === r.id
              const showIcon = r.status !== 'done'
              return (
                <a
                  key={r.id}
                  href={href({ page: 'run', id: r.id })}
                  title={[r.instance, timeAgo(r.createdAt)].filter(Boolean).join(' - ')}
                  className={cn(
                    'flex h-8 items-center gap-2 rounded-lg px-2.5 text-[13px] transition-colors',
                    active ? 'text-fg bg-black/[0.06]' : 'text-text hover:bg-black/[0.04]',
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{r.title}</span>
                  {showIcon ? <StatusIcon status={r.status} className="shrink-0" /> : null}
                </a>
              )
            })}
          </div>
        ))}
        {runs && !runs.length ? (
          <div className="text-faint px-2.5 py-2 text-[12px]">Your runs appear here.</div>
        ) : null}
      </div>

      <div className="p-2">
        <a href="#/settings" className={item(route.page === 'settings')}>
          <Settings className="size-4" />
          <span className="flex-1">Settings</span>
          {user ? (
            <span className="text-faint truncate text-[11.5px] font-normal">{user}</span>
          ) : null}
        </a>
      </div>
    </aside>
  )
}
