import {
  Folder as FolderIcon,
  CaretDoubleLeft as ChevronDoubleLeftIcon,
  CaretDoubleRight as ChevronDoubleRightIcon,
  Checks as DoubleCheckIcon,
  Code as CodeBracketIcon,
  GearSix as Cog6ToothIcon,
  Heartbeat as HeartIcon,
  MapTrifold as MapIcon,
  Plus as PlusIcon,
  CaretUp as ChevronUpIcon,
  PushPin as BookmarkIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '@shared/types.ts'
import mark from '@/assets/ov-mark.svg'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { EditableTitle } from '@/components/common/EditableTitle'
import { type Icon, Skeleton, Spinner } from '@/components/common/ui'
import { TOGGLE_SIDEBAR } from '@/components/layout/CommandPalette'
import { RunMenu, snoozeLabel } from '@/components/run/RunMenu'
import { RUN_STATUS, StatusIcon } from '@/components/run/RunStatus'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useWindowEvent } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { go, href, type Route } from '@/lib/route'
import { refreshRuns, showMoreSettled, sidebarOrder, useRuns, WORKING } from '@/lib/runs'
import { DAY_MS, shortSpan } from '@/lib/time'
import { prefetchRun } from '@/lib/useRun'

const RECENT_LIMIT = 40
const RAIL_RUNS = 12
const BUSY = new Set(['queued', 'running'])
const HOVER_PREFETCH_MS = 150
const TIP_GAP_PX = 10
const AVATAR_PX = 64
const INITIALS_CHARS = 2
const GITHUB_URL = 'https://github.com'
const IN_PROGRESS = 'In progress'
const SETTLED_OPEN_KEY = 'ov-agent.settled-open'
const COLLAPSED_KEY = 'ov-agent.sidebar-collapsed'
const DOCK_QUERY = '(min-width: 1200px)'

const TOOLS = [
  { page: 'map', label: 'Instance map', icon: MapIcon },
  { page: 'health', label: 'Health', icon: HeartIcon },
  { page: 'explorer', label: 'Explorer', icon: CodeBracketIcon },
  { page: 'workspace', label: 'Workspace', icon: FolderIcon },
] as const

function dayLabel(ts: number): string {
  const day = new Date(ts).setHours(0, 0, 0, 0)
  const today = new Date().setHours(0, 0, 0, 0)
  if (day === today) return 'Today'
  if (day === today - DAY_MS) return 'Yesterday'

  const sameYear = new Date(ts).getFullYear() === new Date().getFullYear()
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}

function group(runs: RunSummary[]): [string, RunSummary[]][] {
  const groups = new Map<string, RunSummary[]>()
  const pinned = runs.filter((r) => r.pinned)
  for (const r of runs.filter((x) => !x.pinned)) {
    const label = WORKING.has(r.status) ? IN_PROGRESS : dayLabel(r.createdAt)
    groups.set(label, [...(groups.get(label) ?? []), r])
  }

  const active = groups.get(IN_PROGRESS)
  groups.delete(IN_PROGRESS)
  const rest: [string, RunSummary[]][] = active ? [[IN_PROGRESS, active], ...groups] : [...groups]
  return pinned.length ? [['Pinned', pinned], ...rest] : rest
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
      src={`${GITHUB_URL}/${encodeURIComponent(user)}.png?size=${AVATAR_PX}`}
      alt=""
      onError={() => setBroken(true)}
      className="bg-raised size-8 rounded-full object-cover"
    />
  )
}

function RunMeta({ run }: { run: RunSummary }) {
  if (BUSY.has(run.status)) return <Spinner className="text-brand size-3.5" />
  if (run.status === 'waiting') return <span className="text-warn font-medium">Needs you</span>
  if (run.snoozedUntil)
    return (
      <span title={`Snoozed until ${snoozeLabel(run.snoozedUntil)}`} className="text-brand">
        {shortSpan(run.snoozedUntil - Date.now())}
      </span>
    )

  return <span className="text-faint">{shortSpan(Date.now() - run.updatedAt)}</span>
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
        'group/run animate-slide-in flex h-9 cursor-pointer items-center gap-2 rounded-full pr-1.5 pl-3.5 text-[12.5px] font-medium transition-colors outline-none',
        active
          ? 'bg-brand-soft text-brand-strong'
          : settled
            ? 'text-muted hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas'
            : 'text-text hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas',
        !active && BUSY.has(run.status) && 'opacity-55 hover:opacity-100 focus-visible:opacity-100',
      )}
    >
      <EditableTitle
        value={run.title}
        onSave={async (title) => {
          await api.renameRun(run.id, title)
          await refreshRuns()
        }}
        className="min-w-0 flex-1 truncate"
        inputClassName="h-7 text-[12.5px] font-medium"
      />
      {run.pinned && !settled ? (
        <BookmarkIcon className="text-brand size-3.5 shrink-0 group-hover/run:hidden" />
      ) : null}
      <span className="relative flex h-7 min-w-7 shrink-0 items-center justify-end text-[11.5px] font-normal tabular-nums">
        <span className="pr-1 group-focus-within/run:invisible group-hover/run:invisible">
          <RunMeta run={run} />
        </span>
        <span className="absolute inset-y-0 right-0 flex items-center">
          <RunMenu run={run} settled={Boolean(settled)} inRow />
        </span>
      </span>
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
        .slice(0, INITIALS_CHARS)
        .map((w) => w[0])
        .join('') || title.trim().slice(0, INITIALS_CHARS)
    ).toUpperCase() || '#'
  )
}

function RailRun({ run, active }: { run: RunSummary; active: boolean }) {
  const tip = useRailTip()
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
        tip.show(e)
        hover.start()
      }}
      onMouseLeave={() => {
        tip.hide()
        hover.stop()
      }}
      className={cn(
        'group/rail animate-fade-in relative mx-auto flex size-9 items-center justify-center transition-opacity',
        !active && BUSY.has(run.status) && 'opacity-55 hover:opacity-100',
      )}
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
      <RailTip at={tip.at}>
        <span className="line-clamp-2">{run.title}</span>
        <span className="text-muted mt-0.5 flex items-center gap-1.5 text-[11.5px] font-normal">
          <StatusIcon status={run.status} className="size-3" />
          {RUN_STATUS[run.status].text}
        </span>
      </RailTip>
    </a>
  )
}

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

type TipAt = { x: number; y: number }

function useRailTip() {
  const [at, setAt] = useState<TipAt>()

  return {
    at,
    show: (e: React.MouseEvent<HTMLElement>) => {
      const box = e.currentTarget.getBoundingClientRect()
      setAt({ x: box.right + TIP_GAP_PX, y: box.top + box.height / 2 })
    },
    hide: () => setAt(undefined),
  }
}

function RailTip({ at, children }: { at?: TipAt; children: ReactNode }) {
  if (!at) return null

  return createPortal(
    <div
      role="tooltip"
      className="animate-tip border-line-strong/70 text-fg pointer-events-none fixed z-[60] flex max-w-[260px] -translate-y-1/2 flex-col rounded-xl border bg-white px-3 py-1.5 text-[12.5px] leading-snug font-medium shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
      style={{ left: at.x, top: at.y }}
    >
      <span className="border-line-strong/70 absolute top-1/2 -left-[5px] size-2.5 -translate-y-1/2 rotate-45 border-b border-l bg-white" />
      {children}
    </div>,
    document.body,
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
  const tip = useRailTip()

  return (
    <a
      href={to}
      aria-label={collapsed ? label : undefined}
      onMouseEnter={collapsed ? tip.show : undefined}
      onMouseLeave={tip.hide}
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
      {collapsed ? (
        <RailTip at={tip.at}>{label}</RailTip>
      ) : (
        <span className="truncate">{label}</span>
      )}
    </a>
  )
}

function ShelfToggle({
  label,
  count,
  open,
  onClick,
}: {
  label: string
  count: number
  open: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className={cn(
        'flex h-8 w-full shrink-0 items-center gap-3 px-3.5 text-[12px] font-medium transition-colors',
        open ? 'text-brand-strong' : 'text-faint hover:text-fg',
      )}
    >
      <span className="shrink-0">
        {label} <span className="tabular-nums">({count})</span>
      </span>
      <span className={cn('h-px flex-1', open ? 'bg-brand/30' : 'bg-line-strong/60')} />
      <ChevronUpIcon
        className={cn('size-3 shrink-0 transition-transform duration-200', !open && 'rotate-180')}
      />
    </button>
  )
}

export function Sidebar({ route, user }: { route: Route; user?: string }) {
  const list = useRuns()
  const [showAll, setShowAll] = useState(false)
  const [pinnedCollapsed, setCollapsed] = useState(storedCollapsed)
  const [drawer, setDrawer] = useState(false)
  const [snoozedOpen, setSnoozedOpen] = useState(false)
  const [settledOpen, setSettledOpen] = useState(
    () => localStorage.getItem(SETTLED_OPEN_KEY) === '1',
  )
  const toggleTip = useRailTip()
  const moreTip = useRailTip()
  const settledTip = useRailTip()
  const settingsTip = useRailTip()
  const docked = useDocked()
  const collapsed = docked ? pinnedCollapsed : !drawer
  const overlay = !docked && drawer
  const routeKey = JSON.stringify(route)

  useEffect(() => setDrawer(false), [routeKey, docked])
  useLayer(() => setDrawer(false), overlay)

  const active = list?.active ?? []
  const settled = list?.settled ?? []
  const snoozed = list?.snoozed ?? []
  const settledTotal = list?.settledTotal ?? 0
  const ordered = sidebarOrder(active)
  const shown = showAll ? ordered : ordered.slice(0, RECENT_LIMIT)
  const onSettings = route.page === 'settings'
  const isOpen = (id: string) => route.page === 'run' && route.id === id

  const toggleSettled = (open = !settledOpen) => {
    localStorage.setItem(SETTLED_OPEN_KEY, open ? '1' : '0')
    setSettledOpen(open)
  }

  const toggle = () => {
    toggleTip.hide()
    if (!docked) return setDrawer((d) => !d)

    setCollapsed((c) => {
      localStorage.setItem(COLLAPSED_KEY, c ? '0' : '1')
      return !c
    })
  }

  useWindowEvent(TOGGLE_SIDEBAR, toggle)

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
            ? 'animate-slide-in fixed inset-y-0 left-0 z-50 w-[352px] shadow-[0_12px_40px_rgba(38,50,56,0.22)]'
            : 'relative',
          !overlay && (collapsed ? 'w-[72px]' : 'w-[352px]'),
        )}
      >
        <div
          className={cn(
            'flex h-16 shrink-0 items-center overflow-hidden',
            collapsed ? 'justify-center' : 'justify-between pr-3 pl-5',
          )}
        >
          {collapsed ? (
            <button
              type="button"
              onClick={toggle}
              aria-label="Expand sidebar"
              onMouseEnter={toggleTip.show}
              onMouseLeave={toggleTip.hide}
              className="group/logo hover:bg-brand-soft relative flex size-10 items-center justify-center rounded-full transition-colors"
            >
              <img
                src={mark}
                alt=""
                className="h-[26px] w-auto transition-opacity group-hover/logo:opacity-0"
              />
              <ChevronDoubleRightIcon className="text-brand-strong absolute size-4 opacity-0 transition-opacity group-hover/logo:opacity-100" />
              <RailTip at={toggleTip.at}>Expand sidebar</RailTip>
            </button>
          ) : (
            <>
              <a href="#/" aria-label="OV Agent home">
                <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto max-w-none" />
              </a>
              <button
                type="button"
                onClick={toggle}
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
                className="text-faint hover:bg-canvas hover:text-brand-strong flex size-8 items-center justify-center rounded-full transition-colors"
              >
                <ChevronDoubleLeftIcon className="size-4" />
              </button>
            </>
          )}
        </div>
        <nav className={cn('shrink-0 px-3 pb-2', collapsed ? 'space-y-1.5' : 'space-y-0.5')}>
          <NavRow
            to="#/"
            icon={PlusIcon}
            label="New run"
            active={route.page === 'home'}
            collapsed={collapsed}
          />
          {TOOLS.map((tool) => (
            <NavRow
              key={tool.page}
              to={href({ page: tool.page })}
              icon={tool.icon}
              label={tool.label}
              active={route.page === tool.page}
              collapsed={collapsed}
            />
          ))}
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
                  onMouseEnter={moreTip.show}
                  onMouseLeave={moreTip.hide}
                  className="text-faint hover:text-brand-strong hover:bg-canvas relative mx-auto flex size-9 items-center justify-center rounded-full text-[11px] font-medium"
                >
                  +{active.length - RAIL_RUNS}
                  <RailTip at={moreTip.at}>Show all threads</RailTip>
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

          {snoozed.length && !collapsed ? (
            <div
              className={cn(
                'flex min-h-0 flex-col px-3 pt-1 pb-2',
                snoozedOpen ? 'max-h-[30%] shrink' : 'shrink-0',
              )}
            >
              <ShelfToggle
                label="Snoozed"
                count={snoozed.length}
                open={snoozedOpen}
                onClick={() => setSnoozedOpen((v) => !v)}
              />
              {snoozedOpen ? (
                <div className="animate-fade-in mt-1 min-h-0 flex-1 scrollbar-thin space-y-0.5 overflow-y-auto">
                  {snoozed.map((r) => (
                    <RunItem key={r.id} run={r} active={isOpen(r.id)} />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {settledTotal ? (
            collapsed ? (
              <div className="flex shrink-0 justify-center pb-2">
                <button
                  type="button"
                  onClick={openSettled}
                  onMouseEnter={settledTip.show}
                  onMouseLeave={settledTip.hide}
                  className="text-faint hover:text-ok hover:bg-canvas relative flex h-8 items-center gap-1 rounded-full px-2 text-[11px] font-medium transition-colors"
                >
                  <DoubleCheckIcon aria-hidden className="size-3.5" />
                  {settledTotal}
                  <RailTip at={settledTip.at}>Settled threads</RailTip>
                </button>
              </div>
            ) : (
              <div
                className={cn(
                  'flex min-h-0 flex-col px-3 pt-1 pb-2',
                  settledOpen ? 'max-h-[45%] min-h-[88px] shrink' : 'shrink-0',
                )}
              >
                <ShelfToggle
                  label="Settled"
                  count={settledTotal}
                  open={settledOpen}
                  onClick={() => toggleSettled()}
                />
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
              onMouseEnter={settingsTip.show}
              onMouseLeave={settingsTip.hide}
              className={cn(
                'relative flex size-11 items-center justify-center rounded-full transition-colors',
                onSettings ? 'bg-brand-soft' : 'hover:bg-canvas',
              )}
            >
              <Avatar user={user} />
              <RailTip at={settingsTip.at}>Settings</RailTip>
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
              title="Settings"
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
