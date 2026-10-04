import {
  CircleAlert,
  CircleCheck,
  CircleSlash,
  MessageSquareText,
  Plus,
  Settings,
  Trash2,
} from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import type { RunStatus, RunSummary } from '@shared/types.ts'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { dialog } from '@/components/Dialog'
import { Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href, type Route } from '@/lib/route'

const RECENT_LIMIT = 40
const PANEL_KEY = 'ov-agent.panel-open'

export function StatusIcon({
  status,
  className,
  detailed,
}: {
  status: RunStatus
  className?: string
  detailed?: boolean
}) {
  if (status === 'running' || status === 'queued')
    return <Spinner className={cn('text-brand size-3', className)} />
  if (detailed && status === 'done')
    return <CircleCheck className={cn('text-ok size-3.5', className)} />
  if (detailed && status === 'cancelled')
    return <CircleSlash className={cn('text-faint size-3.5', className)} />
  if (detailed && status === 'error')
    return <CircleAlert className={cn('text-danger size-3.5', className)} />
  const dot: Record<string, string> = {
    waiting: 'bg-warn',
    error: 'bg-danger',
    cancelled: 'bg-line-strong',
    done: 'bg-ok',
  }
  return <span className={cn('block size-1.5 rounded-full', dot[status], className)} />
}

function dayLabel(ts: number): string {
  const day = new Date(ts).setHours(0, 0, 0, 0)
  const today = new Date().setHours(0, 0, 0, 0)
  if (day === today) return 'Today'
  if (day === today - 86_400_000) return 'Yesterday'
  const sameYear = new Date(ts).getFullYear() === new Date().getFullYear()
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}

function group(runs: RunSummary[]): [string, RunSummary[]][] {
  const groups = new Map<string, RunSummary[]>()
  for (const r of runs) {
    const label = ['queued', 'running', 'waiting'].includes(r.status)
      ? 'In progress'
      : dayLabel(r.createdAt)
    groups.set(label, [...(groups.get(label) ?? []), r])
  }
  const active = groups.get('In progress')
  groups.delete('In progress')
  return active ? [['In progress', active], ...groups] : [...groups]
}

function useRuns(): RunSummary[] | undefined {
  const [runs, setRuns] = useState<RunSummary[]>()
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .runs()
        .then((r) => alive && setRuns(r))
        .catch(() => undefined)
    load()
    const timer = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])
  return runs
}

function RailButton({
  label,
  active,
  onClick,
  to,
  children,
}: {
  label: string
  active?: boolean
  onClick?: () => void
  to?: string
  children: ReactNode
}) {
  const className = cn(
    'group/rail relative flex size-10 items-center justify-center rounded-xl text-white transition-colors',
    active ? 'bg-white/20' : 'hover:bg-white/20',
  )
  const inner = (
    <>
      {children}
      {active && to ? (
        <span className="absolute top-1/2 -left-2 h-4 w-1 -translate-y-1/2 rounded-r-full bg-white" />
      ) : null}
      <span className="bg-fg pointer-events-none absolute top-1/2 left-full z-50 ml-3 -translate-y-1/2 rounded-full px-2.5 py-1 text-[12px] font-medium whitespace-nowrap text-white opacity-0 shadow-[0_4px_6px_rgba(0,0,0,0.1)] transition-opacity group-hover/rail:opacity-100">
        {label}
      </span>
    </>
  )
  return to ? (
    <a href={to} aria-label={label} className={className}>
      {inner}
    </a>
  ) : (
    <button type="button" aria-label={label} onClick={onClick} className={className}>
      {inner}
    </button>
  )
}

function Avatar({ user }: { user?: string }) {
  const [broken, setBroken] = useState(false)
  if (!user || broken)
    return (
      <span className="text-brand-strong flex size-8 items-center justify-center rounded-full bg-white text-[13px] font-semibold">
        {(user ?? '?').slice(0, 1).toUpperCase()}
      </span>
    )
  return (
    <img
      src={`https://github.com/${encodeURIComponent(user)}.png?size=64`}
      alt=""
      onError={() => setBroken(true)}
      className="size-8 rounded-full object-cover ring-2 ring-white/60"
    />
  )
}

function RunItem({ run, active }: { run: RunSummary; active: boolean }) {
  const remove = async (e: React.MouseEvent) => {
    e.preventDefault()
    const ok = await dialog.confirm({
      title: 'Delete this run?',
      body: 'The conversation, findings and proposed changes are removed. This cannot be undone.',
      confirmLabel: 'Delete',
      tone: 'danger',
    })
    if (!ok) return
    await api.deleteRun(run.id)
    if (active) go({ page: 'home' })
  }

  return (
    <a
      href={href({ page: 'run', id: run.id })}
      title={[run.title, run.instance, timeAgo(run.createdAt)].filter(Boolean).join(' - ')}
      className={cn(
        'group/run flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-[12.5px] font-medium transition-colors',
        active
          ? 'bg-brand-soft text-brand-strong'
          : 'text-text hover:bg-canvas hover:text-brand-strong',
      )}
    >
      <span className="flex size-3 shrink-0 items-center justify-center">
        <StatusIcon status={run.status} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate">{run.title}</span>
        {run.instance ? (
          <span className="text-faint block truncate text-[11px] font-normal">{run.instance}</span>
        ) : null}
      </span>
      <button
        type="button"
        aria-label="Delete run"
        onClick={(e) => void remove(e)}
        className="text-faint hover:text-danger hidden size-6 shrink-0 items-center justify-center rounded-lg group-hover/run:flex hover:bg-white"
      >
        <Trash2 className="size-3.5" />
      </button>
    </a>
  )
}

export function Sidebar({ route, user }: { route: Route; user?: string }) {
  const runs = useRuns()
  const [open, setOpen] = useState(() => localStorage.getItem(PANEL_KEY) !== '0')
  const [showAll, setShowAll] = useState(false)
  useEffect(() => localStorage.setItem(PANEL_KEY, open ? '1' : '0'), [open])

  const shown = showAll ? (runs ?? []) : (runs ?? []).slice(0, RECENT_LIMIT)

  return (
    <div className="flex h-full shrink-0">
      <nav className="bg-brand flex w-14 shrink-0 flex-col items-center gap-1.5 py-3">
        <a
          href="#/"
          aria-label="OV Agent home"
          className="mb-3 flex size-10 items-center justify-center overflow-hidden rounded-xl shadow-[0_2px_6px_rgba(0,0,0,0.12)]"
        >
          <img src="/favicon.svg" alt="" className="size-10" />
        </a>
        <RailButton
          label={open ? 'Hide runs' : 'Show runs'}
          active={open}
          onClick={() => setOpen(!open)}
        >
          <MessageSquareText className="size-5" strokeWidth={1.75} />
        </RailButton>
        <RailButton label="New run" to="#/" active={route.page === 'home'}>
          <Plus className="size-5" strokeWidth={2} />
        </RailButton>
        <div className="flex-1" />
        <RailButton
          label="Settings"
          to={href({ page: 'settings' })}
          active={route.page === 'settings'}
        >
          <Settings className="size-5" strokeWidth={1.75} />
        </RailButton>
        <a href={href({ page: 'settings' })} title={user ?? 'Settings'} className="mt-1.5">
          <Avatar user={user} />
        </a>
      </nav>

      {open ? (
        <aside className="border-line-strong/60 flex w-[268px] shrink-0 flex-col border-r bg-white">
          <div className="flex h-16 shrink-0 items-center px-5">
            <a href="#/" aria-label="OV Agent home">
              <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto" />
            </a>
          </div>
          <div className="px-3 pb-2">
            <a
              href="#/"
              className="bg-brand hover:bg-brand-strong flex h-10 items-center justify-center gap-2 rounded-xl text-[13px] font-medium text-white transition-colors"
            >
              <Plus className="size-4" strokeWidth={2.25} /> New run
            </a>
          </div>

          <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto px-3 pt-2 pb-4">
            {!runs ? (
              <div className="space-y-4 px-2.5 pt-3">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
                ))}
              </div>
            ) : null}
            {group(shown).map(([label, list], index) => (
              <div key={label} className={index ? 'mt-5' : 'mt-1'}>
                <div className="text-faint mb-1 px-2.5 text-[12px] font-medium">{label}</div>
                <div className="space-y-0.5">
                  {list.map((r) => (
                    <RunItem
                      key={r.id}
                      run={r}
                      active={route.page === 'run' && route.id === r.id}
                    />
                  ))}
                </div>
              </div>
            ))}
            {!showAll && (runs?.length ?? 0) > RECENT_LIMIT ? (
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className="text-brand-strong hover:bg-canvas mt-3 w-full rounded-xl px-2.5 py-2 text-left text-[12.5px] font-medium"
              >
                Show all {runs?.length} runs
              </button>
            ) : null}
            {runs && !runs.length ? (
              <div className="text-faint px-2.5 py-3 text-[12.5px]">
                Your runs appear here. Start one with a case number or a question.
              </div>
            ) : null}
          </div>
        </aside>
      ) : null}
    </div>
  )
}
