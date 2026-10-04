import {
  BookOpen,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleSlash,
  FolderGit2,
  PanelLeft,
  Plus,
  Search,
  Server,
  Settings,
  Trash2,
  X,
} from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import type { RunStatus, RunSummary } from '@shared/types.ts'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { dialog } from '@/components/Dialog'
import { Skeleton, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href, type Route } from '@/lib/route'

const RECENT_LIMIT = 30
const COLLAPSED_KEY = 'ov-agent.sidebar-collapsed'

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
    cancelled: 'border border-line-strong',
    done: 'border border-faint/60',
  }
  return <span className={cn('block size-2 rounded-full', dot[status], className)} />
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
      ? 'Working'
      : dayLabel(r.createdAt)
    groups.set(label, [...(groups.get(label) ?? []), r])
  }
  const working = groups.get('Working')
  groups.delete('Working')
  return working ? [['Working', working], ...groups] : [...groups]
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

function NavItem({
  to,
  active,
  icon,
  label,
  collapsed,
  badge,
}: {
  to: string
  active: boolean
  icon: ReactNode
  label: string
  collapsed: boolean
  badge?: ReactNode
}) {
  return (
    <a
      href={to}
      title={collapsed ? label : undefined}
      className={cn(
        'flex h-9 items-center gap-3 rounded-full text-[13.5px] transition-colors',
        collapsed ? 'w-9 justify-center' : 'px-3',
        active ? 'text-fg bg-black/[0.07] font-medium' : 'text-text hover:bg-black/[0.04]',
      )}
    >
      <span className="text-muted flex size-5 shrink-0 items-center justify-center">{icon}</span>
      {collapsed ? null : <span className="flex-1 truncate">{label}</span>}
      {collapsed ? null : badge}
    </a>
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
        'group/run flex h-9 items-center gap-3 rounded-full px-3 text-[13px] transition-colors',
        active ? 'text-fg bg-black/[0.07]' : 'text-text hover:bg-black/[0.04]',
      )}
    >
      <span className="flex size-5 shrink-0 items-center justify-center">
        <StatusIcon status={run.status} />
      </span>
      <span className="min-w-0 flex-1 truncate">{run.title}</span>
      <button
        type="button"
        aria-label="Delete run"
        onClick={(e) => void remove(e)}
        className="text-faint hover:text-danger -mr-1 hidden size-6 shrink-0 items-center justify-center rounded-full group-hover/run:flex hover:bg-white"
      >
        <Trash2 className="size-3.5" />
      </button>
    </a>
  )
}

function Avatar({ user }: { user?: string }) {
  const [broken, setBroken] = useState(false)
  if (!user || broken)
    return (
      <span className="bg-brand-soft text-brand-strong flex size-8 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold">
        {(user ?? '?').slice(0, 1).toUpperCase()}
      </span>
    )
  return (
    <img
      src={`https://github.com/${encodeURIComponent(user)}.png?size=64`}
      alt=""
      onError={() => setBroken(true)}
      className="bg-raised size-8 shrink-0 rounded-full object-cover"
    />
  )
}

export function Sidebar({
  route,
  user,
  instances,
}: {
  route: Route
  user?: string
  instances?: { valid: number; total: number }
}) {
  const runs = useRuns()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [searching, setSearching] = useState(false)
  const [query, setQuery] = useState('')
  const [showAll, setShowAll] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0'), [collapsed])
  useEffect(() => {
    if (searching) searchRef.current?.focus()
  }, [searching])

  const startSearch = () => {
    setCollapsed(false)
    setSearching(true)
  }
  const filtered = (runs ?? []).filter(
    (r) => !query || `${r.title} ${r.instance ?? ''}`.toLowerCase().includes(query.toLowerCase()),
  )
  const shown = showAll || query ? filtered : filtered.slice(0, RECENT_LIMIT)

  return (
    <aside
      className={cn(
        'bg-canvas border-line-strong/40 flex shrink-0 flex-col border-r transition-[width] duration-200',
        collapsed ? 'w-[60px] items-center' : 'w-[272px]',
      )}
    >
      <div
        className={cn(
          'flex h-16 shrink-0 items-center',
          collapsed ? 'justify-center' : 'justify-between pr-2.5 pl-4',
        )}
      >
        {collapsed ? null : (
          <a href="#/" aria-label="OV Agent home" className="flex items-center">
            <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto" />
          </a>
        )}
        <button
          type="button"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          onClick={() => setCollapsed(!collapsed)}
          className="text-muted hover:text-fg flex size-9 items-center justify-center rounded-full hover:bg-black/[0.05]"
        >
          <PanelLeft className="size-[18px]" />
        </button>
      </div>

      <nav className={cn('space-y-0.5', collapsed ? 'flex flex-col items-center' : 'px-2.5')}>
        <a
          href="#/"
          title={collapsed ? 'New run' : undefined}
          className={cn(
            'group/new mb-1 flex h-10 items-center gap-3 rounded-full text-[13.5px] font-medium transition-colors',
            collapsed ? 'w-10 justify-center' : 'px-1.5',
            route.page === 'home' ? 'text-fg' : 'text-text',
          )}
        >
          <span className="bg-brand group-hover/new:bg-brand-strong flex size-7 shrink-0 items-center justify-center rounded-full text-white shadow-sm transition-colors">
            <Plus className="size-4" />
          </span>
          {collapsed ? null : 'New run'}
        </a>
        <NavItem
          to={href({ page: 'instances' })}
          active={route.page === 'instances'}
          icon={<Server className="size-4" />}
          label="Instances"
          collapsed={collapsed}
          badge={
            instances?.total ? (
              <span className="text-faint text-[11.5px]">
                {instances.valid}/{instances.total}
              </span>
            ) : null
          }
        />
        <NavItem
          to={href({ page: 'skills' })}
          active={route.page === 'skills'}
          icon={<BookOpen className="size-4" />}
          label="Skills"
          collapsed={collapsed}
        />
        <NavItem
          to={href({ page: 'sources' })}
          active={route.page === 'sources'}
          icon={<FolderGit2 className="size-4" />}
          label="Sources"
          collapsed={collapsed}
        />
      </nav>

      {collapsed ? (
        <div className="flex-1" />
      ) : (
        <div className="mt-5 min-h-0 flex-1 scrollbar-thin overflow-y-auto px-2.5 pb-3">
          {searching ? (
            <div className="border-line-strong focus-within:border-brand mb-3 flex h-9 items-center gap-2 rounded-full border bg-white px-3">
              <Search className="text-faint size-3.5 shrink-0" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setQuery('')
                    setSearching(false)
                  }
                }}
                placeholder="Search runs"
                className="placeholder:text-faint w-full bg-transparent text-[13px] outline-none"
              />
              <button
                type="button"
                aria-label="Close search"
                onClick={() => {
                  setQuery('')
                  setSearching(false)
                }}
                className="text-faint hover:text-fg"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ) : null}

          {!runs ? (
            <div className="space-y-3.5 px-3 pt-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} dim className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
              ))}
            </div>
          ) : null}
          {group(shown).map(([label, list]) => (
            <div key={label} className="mb-4">
              <div className="text-faint px-3 pb-1 text-[12px] font-medium">{label}</div>
              {list.map((r) => (
                <RunItem key={r.id} run={r} active={route.page === 'run' && route.id === r.id} />
              ))}
            </div>
          ))}
          {!showAll && !query && filtered.length > RECENT_LIMIT ? (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="text-muted hover:text-fg flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] hover:bg-black/[0.04]"
            >
              <ChevronDown className="size-3.5" /> Show all {filtered.length}
            </button>
          ) : null}
          {runs && !filtered.length ? (
            <div className="text-faint px-3 py-2 text-[12.5px]">
              {query ? 'No runs match.' : 'Your runs appear here.'}
            </div>
          ) : null}
        </div>
      )}

      <div
        className={cn(
          'border-line-strong/50 flex h-16 shrink-0 items-center border-t',
          collapsed ? 'w-full flex-col justify-center gap-1 py-3' : 'gap-2.5 pr-2 pl-3',
        )}
      >
        {collapsed ? (
          <a href={href({ page: 'settings' })} title={user ?? 'Settings'}>
            <Avatar user={user} />
          </a>
        ) : (
          <>
            <a
              href={href({ page: 'settings' })}
              className="flex min-w-0 flex-1 items-center gap-2.5 rounded-full py-1 pr-2 hover:opacity-80"
            >
              <Avatar user={user} />
              <span className="min-w-0">
                <span className="text-fg block truncate text-[13px] font-medium">
                  {user ?? 'Not signed in'}
                </span>
                <span className="text-faint block text-[11.5px]">GitHub Copilot</span>
              </span>
            </a>
            <button
              type="button"
              aria-label="Search runs"
              title="Search runs"
              onClick={startSearch}
              className="text-muted hover:text-fg flex size-9 items-center justify-center rounded-full hover:bg-black/[0.05]"
            >
              <Search className="size-4" />
            </button>
            <a
              href={href({ page: 'settings' })}
              aria-label="Settings"
              title="Settings"
              className={cn(
                'flex size-9 items-center justify-center rounded-full hover:bg-black/[0.05]',
                route.page === 'settings' ? 'text-fg bg-black/[0.07]' : 'text-muted hover:text-fg',
              )}
            >
              <Settings className="size-4" />
            </a>
          </>
        )}
      </div>
    </aside>
  )
}
