import {
  CheckCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CodeBracketIcon,
  Cog6ToothIcon,
  ExclamationCircleIcon,
  HeartIcon,
  MapIcon,
  NoSymbolIcon,
  PlusIcon,
  TrashIcon,
} from '@heroicons/react/24/outline'
import type { Icon } from '@/components/ui'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunStatus, RunSummary } from '@shared/types.ts'
import mark from '@/assets/ov-mark.svg'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { dialog } from '@/components/Dialog'
import { EditableTitle } from '@/components/EditableTitle'
import { Skeleton, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href, type Route } from '@/lib/route'
import { useSettings } from '@/lib/settings'

const RECENT_LIMIT = 40
const RUNS_POLL_MS = 3000

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
    return <CheckCircleIcon className={cn('text-ok size-3.5', className)} />
  if (detailed && status === 'cancelled')
    return <NoSymbolIcon className={cn('text-faint size-3.5', className)} />
  if (detailed && status === 'error')
    return <ExclamationCircleIcon className={cn('text-danger size-3.5', className)} />

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

function useRuns(): [RunSummary[] | undefined, () => void] {
  const [runs, setRuns] = useState<RunSummary[]>()
  const load = useCallback(() => {
    api
      .runs()
      .then(setRuns)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, RUNS_POLL_MS)
    return () => clearInterval(timer)
  }, [load])

  return [runs, load]
}

const BUSY = new Set(['queued', 'running'])
const NOTICE: Partial<Record<RunStatus, string>> = {
  done: 'Run finished',
  error: 'Run failed',
  waiting: 'Run needs you',
}

function useRunNotifications(runs: RunSummary[] | undefined, enabled: boolean) {
  const previous = useRef(new Map<string, RunStatus>())

  useEffect(() => {
    if (!runs) return

    const before = previous.current
    previous.current = new Map(runs.map((r) => [r.id, r.status]))
    const tabInBackground = document.visibilityState === 'hidden'
    const allowed =
      enabled &&
      before.size > 0 &&
      tabInBackground &&
      'Notification' in window &&
      Notification.permission === 'granted'
    if (!allowed) return

    for (const run of runs) {
      const was = before.get(run.id)
      const title = NOTICE[run.status]
      if (!was || !BUSY.has(was) || !title) continue
      const notice = new Notification(title, { body: run.title, icon: '/favicon-32.png' })
      notice.onclick = () => {
        window.focus()
        go({ page: 'run', id: run.id })
      }
    }
  }, [runs, enabled])
}

function Avatar({ user }: { user?: string }) {
  const [broken, setBroken] = useState(false)

  if (!user || broken)
    return (
      <span className="bg-brand-soft text-brand-strong flex size-8 items-center justify-center rounded-full text-[13px] font-semibold">
        {(user ?? '?').slice(0, 1).toUpperCase()}
      </span>
    )
  return (
    <img
      src={`https://github.com/${encodeURIComponent(user)}.png?size=64`}
      alt=""
      onError={() => setBroken(true)}
      className="bg-raised size-8 rounded-full object-cover"
    />
  )
}

function RunItem({
  run,
  active,
  onChanged,
}: {
  run: RunSummary
  active: boolean
  onChanged: () => void
}) {
  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const ok = await dialog.confirm({
      title: 'Delete this run?',
      body: 'The conversation, findings and proposed changes are removed. This cannot be undone.',
      confirmLabel: 'Delete',
      tone: 'danger',
    })
    if (!ok) return

    await api.deleteRun(run.id)
    onChanged()
    if (active) go({ page: 'home' })
  }

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => go({ page: 'run', id: run.id })}
      onKeyDown={(e) => e.key === 'Enter' && go({ page: 'run', id: run.id })}
      className={cn(
        'group/run flex h-9 cursor-pointer items-center gap-2.5 rounded-full pr-1 pl-3.5 text-[12.5px] font-medium transition-colors outline-none',
        active
          ? 'bg-brand-soft text-brand-strong'
          : 'text-text hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas',
      )}
    >
      <span className="flex size-3 shrink-0 items-center justify-center">
        <StatusIcon status={run.status} />
      </span>
      <EditableTitle
        value={run.title}
        onSave={async (title) => {
          await api.renameRun(run.id, title)
          onChanged()
        }}
        className="min-w-0 flex-1 truncate"
        inputClassName="h-7 text-[12.5px] font-medium"
      />
      <button
        type="button"
        aria-label="Delete run"
        onClick={(e) => void remove(e)}
        className="text-faint hover:text-danger flex size-7 shrink-0 items-center justify-center rounded-full opacity-0 transition-opacity group-hover/run:opacity-100 hover:bg-black/[0.06] focus-visible:opacity-100"
      >
        <TrashIcon className="size-3.5" />
      </button>
    </div>
  )
}

const COLLAPSED_KEY = 'ov-agent.sidebar-collapsed'

export function isSidebarCollapsed(): boolean {
  return localStorage.getItem(COLLAPSED_KEY) === '1'
}

function RailTip({ label }: { label: string }) {
  return (
    <span className="bg-fg pointer-events-none absolute top-1/2 left-full z-50 ml-3 -translate-y-1/2 rounded-full px-3 py-1 text-[12px] font-medium whitespace-nowrap text-white opacity-0 shadow-[0_4px_14px_rgba(38,50,56,0.18)] transition-opacity group-hover/rail:opacity-100">
      {label}
    </span>
  )
}

function NavRow({
  to,
  icon: Icon,
  label,
  active,
  collapsed,
}: {
  to: string
  icon: Icon
  label: string
  active: boolean
  collapsed: boolean
}) {
  return (
    <a
      href={to}
      aria-label={collapsed ? label : undefined}
      className={cn(
        'group/rail relative flex h-9 items-center rounded-full text-[13px] font-medium transition-colors',
        collapsed ? 'mx-auto w-9 justify-center' : 'gap-2.5 pr-3 pl-1.5',
        active
          ? 'bg-brand-soft text-brand-strong'
          : 'text-text hover:bg-canvas hover:text-brand-strong',
      )}
    >
      <span
        className={cn(
          'flex size-6 shrink-0 items-center justify-center rounded-full',
          active ? 'bg-brand text-white' : 'bg-brand-soft text-brand-strong',
        )}
      >
        <Icon className="size-3.5" />
      </span>
      {collapsed ? <RailTip label={label} /> : <span className="truncate">{label}</span>}
    </a>
  )
}

export function Sidebar({ route, user }: { route: Route; user?: string }) {
  const [runs, reload] = useRuns()
  useRunNotifications(runs, useSettings().settings.notify)
  const [showAll, setShowAll] = useState(false)
  const [collapsed, setCollapsed] = useState(isSidebarCollapsed)

  const shown = showAll ? (runs ?? []) : (runs ?? []).slice(0, RECENT_LIMIT)
  const onSettings = route.page === 'settings'
  const toggle = () =>
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSED_KEY, c ? '0' : '1')
      return !c
    })

  return (
    <aside
      className={cn(
        'border-line-strong/60 relative z-20 flex shrink-0 flex-col border-r bg-white transition-[width] duration-200 ease-out',
        collapsed ? 'w-[72px]' : 'w-[272px]',
      )}
    >
      <button
        type="button"
        onClick={toggle}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className="border-line-strong text-muted hover:text-brand-strong hover:border-brand/50 absolute top-1/2 -right-3.5 z-30 flex size-7 -translate-y-1/2 items-center justify-center rounded-full border bg-white shadow-[0_2px_8px_rgba(38,50,56,0.10)] transition-colors"
      >
        {collapsed ? (
          <ChevronRightIcon className="size-3.5" />
        ) : (
          <ChevronLeftIcon className="size-3.5" />
        )}
      </button>
      <div
        className={cn(
          'flex h-16 shrink-0 items-center overflow-hidden',
          collapsed ? 'justify-center' : 'px-5',
        )}
      >
        <a href="#/" aria-label="OV Agent home">
          {collapsed ? (
            <img src={mark} alt="OV Agent" className="h-[26px] w-auto" />
          ) : (
            <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto max-w-none" />
          )}
        </a>
      </div>
      <nav className="space-y-0.5 px-3 pb-2">
        <NavRow
          to="#/"
          icon={PlusIcon}
          label="New run"
          active={route.page === 'home'}
          collapsed={collapsed}
        />
        <NavRow
          to={href({ page: 'map' })}
          icon={MapIcon}
          label="Instance map"
          active={route.page === 'map'}
          collapsed={collapsed}
        />
        <NavRow
          to={href({ page: 'explorer' })}
          icon={CodeBracketIcon}
          label="Explorer"
          active={route.page === 'explorer'}
          collapsed={collapsed}
        />
        <NavRow
          to={href({ page: 'health' })}
          icon={HeartIcon}
          label="Health"
          active={route.page === 'health'}
          collapsed={collapsed}
        />
      </nav>

      <div
        className={cn(
          'min-h-0 flex-1 scrollbar-thin overflow-y-auto px-3 pt-2 pb-4',
          collapsed && 'invisible',
        )}
      >
        {!runs ? (
          <div className="space-y-4 px-3 pt-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
            ))}
          </div>
        ) : null}
        {group(shown).map(([label, list], index) => (
          <div key={label} className={index ? 'mt-5' : 'mt-1'}>
            <div className="text-faint mb-1 px-3.5 text-[12px] font-medium">{label}</div>
            <div className="space-y-0.5">
              {list.map((r) => (
                <RunItem
                  key={r.id}
                  run={r}
                  active={route.page === 'run' && route.id === r.id}
                  onChanged={reload}
                />
              ))}
            </div>
          </div>
        ))}
        {!showAll && (runs?.length ?? 0) > RECENT_LIMIT ? (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="text-brand-strong hover:bg-canvas mt-3 h-9 w-full rounded-full px-3.5 text-left text-[12.5px] font-medium"
          >
            Show all {runs?.length} runs
          </button>
        ) : null}
        {runs && !runs.length ? (
          <div className="text-faint px-3.5 py-3 text-[12.5px]">
            Your runs appear here. Start one with a case number or a question.
          </div>
        ) : null}
      </div>

      {collapsed ? (
        <div className="border-line-strong/60 flex h-16 shrink-0 items-center justify-center border-t">
          <a
            href={href({ page: 'settings' })}
            aria-label="Settings"
            className={cn(
              'group/rail relative flex size-11 items-center justify-center rounded-full transition-colors',
              onSettings ? 'bg-brand-soft' : 'hover:bg-canvas',
            )}
          >
            <Avatar user={user} />
            <RailTip label="Settings" />
          </a>
        </div>
      ) : (
        <div className="border-line-strong/60 flex h-16 shrink-0 items-center gap-1 border-t px-3">
          <a
            href={href({ page: 'settings' })}
            className={cn(
              'flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-full pr-3 pl-1.5 transition-colors',
              onSettings ? 'bg-brand-soft' : 'hover:bg-canvas',
            )}
          >
            <Avatar user={user} />
            <span className="min-w-0">
              <span className="text-fg block truncate text-[13px] font-medium">
                {user ?? 'Not signed in'}
              </span>
              <span className="text-faint block text-[11.5px]">GitHub Copilot</span>
            </span>
          </a>
          <a
            href={href({ page: 'settings' })}
            aria-label="Settings"
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors',
              onSettings
                ? 'bg-brand-soft text-brand-strong'
                : 'text-muted hover:bg-canvas hover:text-fg',
            )}
          >
            <Cog6ToothIcon className="size-[18px]" />
          </a>
        </div>
      )}
    </aside>
  )
}
