import {
  FolderIcon,
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
  ArrowUturnLeftIcon,
  ChevronUpIcon,
} from '@heroicons/react/24/outline'
import type { Icon } from '@/components/ui'
import { useEffect, useRef, useState } from 'react'
import type { RunStatus, RunSummary } from '@shared/types.ts'
import mark from '@/assets/ov-mark.svg'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { DoubleCheckIcon } from '@/components/DoubleCheckIcon'
import { EditableTitle } from '@/components/EditableTitle'
import { notifyInApp } from '@/components/Toasts'
import { Skeleton, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href, type Route } from '@/lib/route'
import { useSettings } from '@/lib/settings'
import { prefetchRun } from '@/lib/useRun'
import { onStatusChange, refreshRuns, setSettled, showMoreSettled, useRuns } from '@/lib/runs'

const RECENT_LIMIT = 40

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

const BUSY = new Set(['queued', 'running'])
const HOVER_PREFETCH_MS = 150
const NOTICE: Partial<Record<RunStatus, string>> = {
  done: 'Run finished',
  error: 'Run failed',
  waiting: 'Run needs you',
}

function useRunNotifications(route: Route, enabled: boolean) {
  const current = useRef(route)
  useEffect(() => {
    current.current = route
  }, [route])

  useEffect(() => {
    if (!enabled) return

    return onStatusChange((change) => {
      const title = change.kind === 'status' && change.status ? NOTICE[change.status] : undefined
      if (!title || !change.id) return
      const id = change.id

      const open = () => {
        window.focus()
        go({ page: 'run', id })
      }
      const focused = document.visibilityState === 'visible' && document.hasFocus()
      const watching = current.current.page === 'run' && current.current.id === id
      if (focused && watching) return
      if (focused || !('Notification' in window) || Notification.permission !== 'granted')
        return notifyInApp(title, change.title ?? '', open)

      const notice = new Notification(title, {
        body: change.title,
        icon: '/favicon-32.png',
        tag: id,
        requireInteraction: change.status === 'waiting',
      })
      notice.onclick = () => {
        notice.close()
        open()
      }
    })
  }, [enabled])
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
  settled,
}: {
  run: RunSummary
  active: boolean
  settled?: boolean
}) {
  const busy = BUSY.has(run.status) || run.status === 'waiting'
  const hover = useHoverPrefetch(run.id, active)

  return (
    <div
      role="link"
      tabIndex={0}
      onMouseEnter={hover.start}
      onMouseLeave={hover.stop}
      onClick={() => go({ page: 'run', id: run.id })}
      onKeyDown={(e) => e.key === 'Enter' && go({ page: 'run', id: run.id })}
      className={cn(
        'group/run animate-slide-in flex h-9 cursor-pointer items-center gap-2.5 rounded-full pr-1 pl-3.5 text-[12.5px] font-medium transition-colors outline-none',
        active
          ? 'bg-brand-soft text-brand-strong'
          : settled
            ? 'text-muted hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas'
            : 'text-text hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas',
      )}
    >
      <span className="flex size-3 shrink-0 items-center justify-center">
        {settled ? (
          <DoubleCheckIcon className="text-ok size-3.5" />
        ) : (
          <StatusIcon status={run.status} />
        )}
      </span>
      <EditableTitle
        value={run.title}
        onSave={async (title) => {
          await api.renameRun(run.id, title)
          await refreshRuns()
        }}
        className="min-w-0 flex-1 truncate"
        inputClassName="h-7 text-[12.5px] font-medium"
      />
      {busy ? null : (
        <button
          type="button"
          title={settled ? 'Move back to active' : 'Settle'}
          aria-label={settled ? 'Move back to active' : 'Settle'}
          onClick={(e) => {
            e.stopPropagation()
            void setSettled(run.id, !settled)
          }}
          className={cn(
            'flex size-7 shrink-0 items-center justify-center rounded-full opacity-0 transition-[opacity,color,background-color] group-hover/run:opacity-100 hover:bg-black/[0.06] focus-visible:opacity-100',
            settled ? 'text-faint hover:text-brand-strong' : 'text-faint hover:text-ok',
          )}
        >
          {settled ? (
            <ArrowUturnLeftIcon className="size-3.5" />
          ) : (
            <DoubleCheckIcon className="size-4" />
          )}
        </button>
      )}
    </div>
  )
}

function useHoverPrefetch(id: string, active: boolean) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  return {
    start: () => {
      if (active) return
      clearTimeout(timer.current)
      timer.current = setTimeout(() => prefetchRun(id), HOVER_PREFETCH_MS)
    },
    stop: () => clearTimeout(timer.current),
  }
}

function initials(title: string): string {
  const words = title.split(/[^A-Za-z0-9]+/).filter((w) => w && !/^\d+$/.test(w))
  return (
    (
      words
        .slice(0, 2)
        .map((w) => w[0])
        .join('') || title.trim().slice(0, 2)
    ).toUpperCase() || '#'
  )
}

function RailRun({ run, active }: { run: RunSummary; active: boolean }) {
  const [tip, setTip] = useState<number>()
  const hover = useHoverPrefetch(run.id, active)
  const tone =
    run.status === 'waiting'
      ? 'ring-warn'
      : run.status === 'error'
        ? 'ring-danger/60'
        : BUSY.has(run.status)
          ? 'ring-brand'
          : 'ring-transparent'

  return (
    <a
      href={href({ page: 'run', id: run.id })}
      aria-label={run.title}
      onMouseEnter={(e) => {
        const box = e.currentTarget.getBoundingClientRect()
        setTip(box.top + box.height / 2)
        hover.start()
      }}
      onMouseLeave={() => {
        setTip(undefined)
        hover.stop()
      }}
      className="group/rail animate-fade-in relative mx-auto flex size-9 items-center justify-center"
    >
      <span
        className={cn(
          'flex size-8 items-center justify-center rounded-full text-[11px] font-semibold tracking-tight ring-2 transition-colors',
          tone,
          active
            ? 'bg-brand text-white'
            : 'bg-raised text-text group-hover/rail:bg-brand-soft group-hover/rail:text-brand-strong',
        )}
      >
        {initials(run.title)}
      </span>
      {BUSY.has(run.status) ? (
        <span className="absolute -right-0.5 -bottom-0.5 flex size-4 items-center justify-center rounded-full bg-white">
          <StatusIcon status={run.status} className="size-3" />
        </span>
      ) : null}
      {tip !== undefined ? (
        <span
          className="bg-fg animate-pop pointer-events-none fixed left-[84px] z-50 max-w-[280px] -translate-y-1/2 truncate rounded-full px-3 py-1 text-[12px] font-medium text-white shadow-[0_4px_14px_rgba(38,50,56,0.18)]"
          style={{ top: tip }}
        >
          {run.title}
        </span>
      ) : null}
    </a>
  )
}

const SETTLED_OPEN_KEY = 'ov-agent.settled-open'
const RAIL_RUNS = 12

const COLLAPSED_KEY = 'ov-agent.sidebar-collapsed'

const DOCK_QUERY = '(min-width: 1200px)'

function storedCollapsed(): boolean {
  return localStorage.getItem(COLLAPSED_KEY) === '1'
}

export function isSidebarCollapsed(): boolean {
  return !matchMedia(DOCK_QUERY).matches || storedCollapsed()
}

function useDocked(): boolean {
  const [docked, setDocked] = useState(() => matchMedia(DOCK_QUERY).matches)

  useEffect(() => {
    const query = matchMedia(DOCK_QUERY)
    const update = () => setDocked(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  return docked
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
        collapsed ? 'mx-auto w-9 justify-center' : 'gap-2.5 pr-3 pl-1',
        active && 'bg-brand-soft text-brand-strong',
        !active && !collapsed && 'text-text hover:bg-canvas hover:text-brand-strong',
      )}
    >
      <span
        className={cn(
          'flex shrink-0 items-center justify-center rounded-full transition-colors',
          collapsed && !active ? 'size-9' : 'size-7',
          active ? 'bg-brand text-white' : 'bg-brand-soft text-brand-strong',
          !active && collapsed && 'group-hover/rail:bg-brand/20',
        )}
      >
        <Icon className="size-3.5" />
      </span>
      {collapsed ? <RailTip label={label} /> : <span className="truncate">{label}</span>}
    </a>
  )
}

export function Sidebar({ route, user }: { route: Route; user?: string }) {
  const list = useRuns()
  useRunNotifications(route, useSettings().settings.notify)
  const [showAll, setShowAll] = useState(false)
  const [pinnedCollapsed, setCollapsed] = useState(storedCollapsed)
  const docked = useDocked()
  const [drawer, setDrawer] = useState(false)
  const collapsed = docked ? pinnedCollapsed : !drawer
  const overlay = !docked && drawer

  const routeKey = JSON.stringify(route)
  useEffect(() => setDrawer(false), [routeKey, docked])

  useEffect(() => {
    if (!overlay) return
    const close = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false)
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [overlay])
  const [settledOpen, setSettledOpen] = useState(
    () => localStorage.getItem(SETTLED_OPEN_KEY) === '1',
  )
  const active = list?.active ?? []
  const settled = list?.settled ?? []
  const settledTotal = list?.settledTotal ?? 0
  const isOpen = (id: string) => route.page === 'run' && route.id === id
  const toggleSettled = (open = !settledOpen) => {
    localStorage.setItem(SETTLED_OPEN_KEY, open ? '1' : '0')
    setSettledOpen(open)
  }

  const shown = showAll ? active : active.slice(0, RECENT_LIMIT)
  const onSettings = route.page === 'settings'
  const toggle = () => {
    if (!docked) return setDrawer((d) => !d)
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSED_KEY, c ? '0' : '1')
      return !c
    })
  }
  const openSettled = () => {
    if (docked) {
      localStorage.setItem(COLLAPSED_KEY, '0')
      setCollapsed(false)
    } else setDrawer(true)
    toggleSettled(true)
  }

  return (
    <>
      {overlay ? (
        <>
          <div className="w-[72px] shrink-0" />
          <div
            aria-hidden
            onClick={() => setDrawer(false)}
            className="animate-fade-in fixed inset-0 z-40 bg-black/20"
          />
        </>
      ) : null}
      <aside
        className={cn(
          'border-line-strong/60 z-20 flex shrink-0 flex-col border-r bg-white transition-[width] duration-200 ease-out',
          overlay
            ? 'animate-slide-in fixed inset-y-0 left-0 z-50 w-[320px] shadow-[0_12px_40px_rgba(38,50,56,0.22)]'
            : 'relative',
          !overlay && (collapsed ? 'w-[72px]' : 'w-[320px]'),
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
        <nav className={cn('shrink-0 px-3 pb-2', collapsed ? 'space-y-1.5' : 'space-y-0.5')}>
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
          <NavRow
            to={href({ page: 'workspace' })}
            icon={FolderIcon}
            label="Workspace"
            active={route.page === 'workspace'}
            collapsed={collapsed}
          />
        </nav>

        <div className="flex min-h-0 flex-1 flex-col">
          {collapsed ? (
            <div className="border-line-strong/60 mt-1 min-h-0 flex-1 scrollbar-thin space-y-1.5 overflow-y-auto border-t px-2 pt-3 pb-3">
              {active.slice(0, RAIL_RUNS).map((r) => (
                <RailRun key={r.id} run={r} active={isOpen(r.id)} />
              ))}
              {active.length > RAIL_RUNS ? (
                <button
                  type="button"
                  onClick={toggle}
                  className="group/rail text-faint hover:text-brand-strong relative mx-auto flex size-9 items-center justify-center rounded-full text-[11px] font-medium"
                >
                  +{active.length - RAIL_RUNS}
                  <RailTip label="Show all threads" />
                </button>
              ) : null}
            </div>
          ) : (
            <div className="min-h-16 flex-1 scrollbar-thin overflow-y-auto px-3 pt-2 pb-4">
              {!list ? (
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
                      <RunItem key={r.id} run={r} active={isOpen(r.id)} />
                    ))}
                  </div>
                </div>
              ))}
              {!showAll && active.length > RECENT_LIMIT ? (
                <button
                  type="button"
                  onClick={() => setShowAll(true)}
                  className="text-brand-strong hover:bg-canvas mt-3 h-9 w-full rounded-full px-3.5 text-left text-[12.5px] font-medium"
                >
                  Show all {active.length} threads
                </button>
              ) : null}
              {list && !active.length ? (
                <div className="text-faint px-3.5 py-3 text-[12.5px]">
                  {settledTotal
                    ? 'Everything is settled. Start a new run with a case number or a question.'
                    : 'Your runs appear here. Start one with a case number or a question.'}
                </div>
              ) : null}
            </div>
          )}

          {settledTotal ? (
            collapsed ? (
              <div className="flex shrink-0 justify-center pb-2">
                <button
                  type="button"
                  onClick={openSettled}
                  className="group/rail text-faint hover:text-ok hover:bg-canvas relative flex h-8 items-center gap-1 rounded-full px-2 text-[11px] font-medium transition-colors"
                >
                  <DoubleCheckIcon className="size-3.5" />
                  {settledTotal}
                  <RailTip label="Settled threads" />
                </button>
              </div>
            ) : (
              <div
                className={cn(
                  'border-line-strong/60 flex min-h-0 flex-col border-t px-3 py-2',
                  settledOpen ? 'max-h-[45%] min-h-[88px] shrink' : 'shrink-0',
                )}
              >
                <button
                  type="button"
                  onClick={() => toggleSettled()}
                  aria-expanded={settledOpen}
                  className="text-muted hover:text-fg hover:bg-canvas flex h-8 w-full shrink-0 items-center gap-2 rounded-full px-3.5 text-[12px] font-medium transition-colors"
                >
                  <DoubleCheckIcon className="text-ok size-3.5" />
                  <span className="flex-1 text-left">Settled</span>
                  <span className="text-faint tabular-nums">{settledTotal}</span>
                  <ChevronUpIcon
                    className={cn(
                      'size-3 transition-transform duration-200',
                      !settledOpen && 'rotate-180',
                    )}
                  />
                </button>
                {settledOpen ? (
                  <div className="animate-fade-in mt-1 min-h-0 flex-1 scrollbar-thin space-y-0.5 overflow-y-auto">
                    {settled.map((r) => (
                      <RunItem key={r.id} run={r} active={isOpen(r.id)} settled />
                    ))}
                    {settledTotal > settled.length ? (
                      <button
                        type="button"
                        onClick={() => void showMoreSettled()}
                        className="text-brand-strong hover:bg-canvas h-8 w-full rounded-full px-3.5 text-left text-[12px] font-medium"
                      >
                        Show more ({settledTotal - settled.length} left)
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            )
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
    </>
  )
}
