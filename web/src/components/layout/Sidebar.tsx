import {
  Alarm as AlarmIcon,
  Bell as BellIcon,
  BellZ as SnoozedIcon,
  Check as CheckIcon,
  CircleNotch as SpinnerIcon,
  Checks as DoubleCheckIcon,
  Code as CodeBracketIcon,
  GearSix as Cog6ToothIcon,
  Heartbeat as HeartIcon,
  MagnifyingGlass as SearchIcon,
  MapTrifold as MapIcon,
  Plus as PlusIcon,
  CaretUp as ChevronUpIcon,
  PushPin as BookmarkIcon,
  SidebarSimple as SidebarIcon,
  WarningCircle as WarningCircleIcon,
} from '@phosphor-icons/react'
import { type ReactNode, type RefObject, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Attention, RunSummary } from '@shared/types.ts'
import mark from '@/assets/ov-mark.svg'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { EditableTitle } from '@/components/common/EditableTitle'
import { AccountButton, type SidebarAccount } from '@/components/layout/AccountMenu'
import { type Icon, PulseDot, Skeleton, SlideIndicator } from '@/components/common/ui'
import { OPEN_PALETTE, TOGGLE_SIDEBAR } from '@/components/layout/CommandPalette'
import { RunMenu } from '@/components/run/RunMenu'
import { RUN_STATUS, StatusIcon } from '@/components/run/RunStatus'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useWindowEvent } from '@/lib/hooks'
import { type Reveal, useFirstLoadReveal, useSlidingIndicator } from '@/lib/motion'
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
const INITIALS_CHARS = 2
const IN_PROGRESS = 'In progress'
const SETTLED_OPEN_KEY = 'ov-agent.settled-open'
const COLLAPSED_KEY = 'ov-agent.sidebar-collapsed'
const SHELF_BUTTON =
  'text-faint hover:bg-canvas relative flex h-8 w-14 items-center justify-center gap-1 rounded-full text-[11px] font-medium tabular-nums transition-colors'
const DOCK_QUERY = '(min-width: 1200px)'
const EXPANDED_WIDTH = 'w-[332px]'
const SEARCH_LABEL = 'Search (Ctrl+K)'
const OPEN_SIDEBAR_LABEL = 'Open sidebar (Ctrl+B)'
const CLOSE_SIDEBAR_LABEL = 'Close sidebar (Ctrl+B)'
const HEADER_BUTTON =
  'text-faint hover:bg-canvas hover:text-brand-strong flex size-8 items-center justify-center rounded-full transition-colors'
const SHELF_PREVIEW = 5
const SHELF_STEP = 10
const SCROLL_EDGE_PX = 2
const CONTENT_INSET = 'px-[11px]'
const ROW_INSET = 'pr-[11px] pl-[11px]'
const GROUP_GAP = 'mt-4'
const FOOTER_INSET = 'pr-[9px] pl-3'
const ACCOUNT_INSET = 'pr-3 pl-2'

type NavTool = { route: Route; label: string; icon: Icon }
type Signal = { label: string; icon: Icon; tone: string }

const WORKING_SIGNAL: Signal = {
  label: 'Working',
  icon: SpinnerIcon,
  tone: 'text-brand animate-spin',
}
const NEEDS_YOU: Signal = { label: 'Needs you', icon: BellIcon, tone: 'text-warn' }
const SNOOZED: Signal = { label: 'Snoozed', icon: SnoozedIcon, tone: 'text-brand' }
const ATTENTION: Record<Attention, Signal> = {
  woke: { label: 'Woke', icon: AlarmIcon, tone: 'text-woke' },
  done: { label: 'Done', icon: CheckIcon, tone: 'text-ok' },
  failed: { label: 'Failed', icon: WarningCircleIcon, tone: 'text-danger' },
}

const TOOLS: NavTool[] = [
  { route: { page: 'map' }, label: 'Instance map', icon: MapIcon },
  { route: { page: 'explorer' }, label: 'Code explorer', icon: CodeBracketIcon },
  { route: { page: 'health' }, label: 'Instance health', icon: HeartIcon },
]

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

function runSignal(run: RunSummary, open: boolean): Signal | undefined {
  if (BUSY.has(run.status)) return WORKING_SIGNAL
  if (run.status === 'waiting') return NEEDS_YOU
  if (!open && run.attention) return ATTENTION[run.attention]
  return run.snoozedUntil ? SNOOZED : undefined
}

function RunTime({ run }: { run: RunSummary }) {
  if (run.snoozedUntil && !BUSY.has(run.status))
    return <span className="text-brand">{shortSpan(run.snoozedUntil - Date.now())}</span>
  return <span className="text-faint">{shortSpan(Date.now() - run.updatedAt)}</span>
}

function RunSignal({ run, open }: { run: RunSummary; open: boolean }) {
  const signal = runSignal(run, open)
  if (!signal) return <span aria-hidden className="bg-line-strong size-1 rounded-full" />

  return (
    <signal.icon
      weight="bold"
      role="img"
      aria-label={signal.label}
      className={cn('size-3.5', signal.tone)}
    />
  )
}

function RunItem({
  run,
  active,
  settled,
  reveal,
}: {
  run: RunSummary
  active: boolean
  settled?: boolean
  reveal?: Reveal
}) {
  const hover = useHoverPrefetch(run.id, active)

  return (
    <div
      role="link"
      tabIndex={0}
      onMouseEnter={hover.start}
      onMouseLeave={hover.stop}
      onClick={() => go({ page: 'thread', id: run.id })}
      onKeyDown={(e) => e.key === 'Enter' && go({ page: 'thread', id: run.id })}
      style={reveal?.style}
      className={cn(
        reveal?.className,
        'group/run flex h-9 cursor-pointer items-center gap-2 rounded-full text-[12.5px] font-medium transition-colors outline-none',
        ROW_INSET,
        active
          ? 'bg-brand-soft text-brand-strong'
          : settled
            ? 'text-muted hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas'
            : 'text-text hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas',
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
      <span className="w-7 shrink-0 text-right text-[11.5px] font-normal tabular-nums">
        <RunTime run={run} />
      </span>
      <span className="relative -mr-1.5 flex size-7 shrink-0 items-center justify-center">
        <span className="flex items-center group-focus-within/run:invisible group-hover/run:invisible">
          <RunSignal run={run} open={active} />
        </span>
        <span className="absolute inset-0 flex items-center justify-center">
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

  const letters =
    words
      .slice(0, INITIALS_CHARS)
      .map((w) => w[0])
      .join('') || title.trim().slice(0, INITIALS_CHARS)

  return letters.toUpperCase() || '#'
}

function RailRun({ run, active, reveal }: { run: RunSummary; active: boolean; reveal?: Reveal }) {
  const tip = useRailTip()
  const hover = useHoverPrefetch(run.id, active)
  const busy = BUSY.has(run.status)
  const signal = runSignal(run, active)

  return (
    <a
      href={href({ page: 'thread', id: run.id })}
      aria-label={run.title}
      onMouseEnter={(e) => {
        tip.show(e)
        hover.start()
      }}
      onMouseLeave={() => {
        tip.hide()
        hover.stop()
      }}
      style={reveal?.style}
      className={cn(
        reveal?.className,
        'group/rail relative mx-auto flex size-9 items-center justify-center',
      )}
    >
      <span
        className={cn(
          'flex size-7 items-center justify-center rounded-full text-[10.5px] font-semibold tracking-tight transition-colors',
          active
            ? 'bg-brand text-white'
            : 'bg-raised text-text group-hover/rail:bg-brand-soft group-hover/rail:text-brand-strong',
        )}
      >
        {initials(run.title)}
      </span>
      {busy || signal ? (
        <span className="absolute right-0 bottom-0 flex size-3.5 items-center justify-center rounded-full bg-white">
          {busy ? (
            <PulseDot className="size-2" />
          ) : signal ? (
            <signal.icon weight="bold" className={cn('size-2.5', signal.tone)} />
          ) : null}
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
  onClick,
  icon: Icon,
  label,
  active,
  collapsed,
}: {
  to?: string
  onClick?: (e: React.MouseEvent<HTMLElement>) => void
  icon: Icon
  label: string
  active: boolean
  collapsed: boolean
}) {
  const tip = useRailTip()
  const Element = to ? 'a' : 'button'

  return (
    <Element
      href={to}
      type={to ? undefined : 'button'}
      onClick={(e: React.MouseEvent<HTMLElement>) => {
        tip.hide()
        onClick?.(e)
      }}
      aria-label={collapsed ? label : undefined}
      data-active={active || undefined}
      onMouseEnter={collapsed ? tip.show : undefined}
      onMouseLeave={tip.hide}
      className={cn(
        'group/rail relative flex items-center text-[13px] font-medium transition-colors',
        collapsed
          ? cn('mx-auto size-9 justify-center rounded-full', !active && 'hover:bg-canvas')
          : cn(
              'h-9 w-full gap-3 rounded-full pr-3 pl-3',
              active ? 'text-brand-strong' : 'text-text hover:bg-canvas hover:text-brand-strong',
            ),
      )}
    >
      <Icon
        weight={active ? 'bold' : 'regular'}
        className={cn(
          'size-[18px] shrink-0 transition-colors',
          active ? 'text-brand-strong' : 'text-muted group-hover/rail:text-brand-strong',
        )}
      />
      {collapsed ? (
        <RailTip at={tip.at}>{label}</RailTip>
      ) : (
        <span className="min-w-0 flex-1 truncate text-left">{label}</span>
      )}
    </Element>
  )
}

function ToolRows({
  tools,
  route,
  collapsed,
}: {
  tools: NavTool[]
  route: Route
  collapsed: boolean
}) {
  return tools.map((tool) => (
    <NavRow
      key={tool.label}
      to={href(tool.route)}
      icon={tool.icon}
      label={tool.label}
      active={route.page === tool.route.page}
      collapsed={collapsed}
    />
  ))
}

function useScrollFades(ref: RefObject<HTMLDivElement | null>): string {
  const [edges, setEdges] = useState({ top: false, bottom: false })

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const measure = () =>
      setEdges({
        top: el.scrollTop > SCROLL_EDGE_PX,
        bottom: el.scrollTop + el.clientHeight < el.scrollHeight - SCROLL_EDGE_PX,
      })

    const resize = new ResizeObserver(measure)
    resize.observe(el)
    for (const child of el.children) resize.observe(child)
    el.addEventListener('scroll', measure, { passive: true })
    measure()

    return () => {
      resize.disconnect()
      el.removeEventListener('scroll', measure)
    }
  }, [ref])

  if (edges.top && edges.bottom) return 'fade-y'
  if (edges.top) return 'fade-top'
  return edges.bottom ? 'fade-bottom' : ''
}

function Shelf({
  label,
  runs,
  total,
  open,
  onToggle,
  onLoadMore,
  settled,
  isOpen,
}: {
  label: string
  runs: RunSummary[]
  total: number
  open: boolean
  onToggle: () => void
  onLoadMore?: () => Promise<void>
  settled?: boolean
  isOpen: (id: string) => boolean
}) {
  const [limit, setLimit] = useState(SHELF_PREVIEW)
  const visible = runs.slice(0, limit)
  const left = total - visible.length

  useEffect(() => {
    if (!open) setLimit(SHELF_PREVIEW)
  }, [open])

  const more = () => {
    const next = limit + SHELF_STEP
    setLimit(next)
    if (onLoadMore && next > runs.length && runs.length < total) void onLoadMore()
  }

  return (
    <section>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(
          'flex h-8 w-full items-center gap-2 text-[12px] font-medium transition-colors',
          CONTENT_INSET,
          open ? 'text-brand-strong' : 'text-faint hover:text-fg',
        )}
      >
        <span className="shrink-0">
          {label} <span className="tabular-nums">({total})</span>
        </span>
        <span className={cn('h-px flex-1', open ? 'bg-brand/30' : 'bg-line-strong/60')} />
        <ChevronUpIcon
          className={cn('size-3 shrink-0 transition-transform duration-200', !open && 'rotate-180')}
        />
      </button>
      {open ? (
        <div className="animate-fade-in mt-1 space-y-0.5">
          {visible.map((r) => (
            <RunItem key={r.id} run={r} active={isOpen(r.id)} settled={settled} />
          ))}
          {left > 0 ? (
            <button
              type="button"
              onClick={more}
              className={cn(
                'text-brand-strong hover:bg-canvas h-8 w-full rounded-full text-left text-[12px] font-medium',
                CONTENT_INSET,
              )}
            >
              Show more ({left} left)
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

export function Sidebar({ route, account }: { route: Route; account?: SidebarAccount }) {
  const list = useRuns()
  const [showAll, setShowAll] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const fades = useScrollFades(scroller)
  const [pinnedCollapsed, setCollapsed] = useState(storedCollapsed)
  const [drawer, setDrawer] = useState(false)
  const [snoozedOpen, setSnoozedOpen] = useState(false)
  const [settledOpen, setSettledOpen] = useState(
    () => localStorage.getItem(SETTLED_OPEN_KEY) === '1',
  )

  const toggleTip = useRailTip()
  const moreTip = useRailTip()
  const settledTip = useRailTip()
  const snoozedTip = useRailTip()
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
  const isOpen = (id: string) => route.page === 'thread' && route.id === id
  const reveal = useFirstLoadReveal(!list)
  const nav = useRef<HTMLElement>(null)
  const navIndicator = useSlidingIndicator(nav, route.page, String(collapsed))

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

  const expand = () => {
    if (!docked) return setDrawer(true)
    localStorage.setItem(COLLAPSED_KEY, '0')
    setCollapsed(false)
  }

  const openSettled = () => {
    expand()
    toggleSettled(true)
  }

  const openSnoozed = () => {
    expand()
    setSnoozedOpen(true)
  }

  const openPalette = () => {
    toggleTip.hide()
    window.dispatchEvent(new Event(OPEN_PALETTE))
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
            ? cn(
                'animate-slide-in fixed inset-y-0 left-0 z-50 shadow-[0_12px_40px_rgba(38,50,56,0.22)]',
                EXPANDED_WIDTH,
              )
            : 'relative',
          !overlay && (collapsed ? 'w-[72px]' : EXPANDED_WIDTH),
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
              aria-label="Open sidebar"
              onMouseEnter={toggleTip.show}
              onMouseLeave={toggleTip.hide}
              className="group/logo hover:bg-brand-soft relative flex size-10 items-center justify-center rounded-full transition-colors"
            >
              <img
                src={mark}
                alt=""
                className="h-[26px] w-auto transition-opacity group-hover/logo:opacity-0"
              />
              <SidebarIcon className="text-brand-strong absolute size-[18px] opacity-0 transition-opacity group-hover/logo:opacity-100" />
              <RailTip at={toggleTip.at}>{OPEN_SIDEBAR_LABEL}</RailTip>
            </button>
          ) : (
            <>
              <a href={href({ page: 'home' })} aria-label="OV Agent home">
                <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto max-w-none" />
              </a>
              <span className="flex items-center gap-0.5">
                <button
                  type="button"
                  onClick={openPalette}
                  aria-label="Search"
                  title={SEARCH_LABEL}
                  className={HEADER_BUTTON}
                >
                  <SearchIcon className="size-[18px]" />
                </button>
                <button
                  type="button"
                  onClick={toggle}
                  aria-label="Close sidebar"
                  title={CLOSE_SIDEBAR_LABEL}
                  className={HEADER_BUTTON}
                >
                  <SidebarIcon className="size-[18px]" />
                </button>
              </span>
            </>
          )}
        </div>
        <nav ref={nav} className="relative shrink-0 space-y-0.5 px-3 pb-2">
          <SlideIndicator indicator={navIndicator} className="bg-brand-soft rounded-full" />
          {collapsed ? (
            <NavRow
              icon={SearchIcon}
              label={SEARCH_LABEL}
              active={false}
              collapsed
              onClick={openPalette}
            />
          ) : null}
          <NavRow
            to={href({ page: 'home' })}
            icon={PlusIcon}
            label="New thread"
            active={route.page === 'home'}
            collapsed={collapsed}
          />
          <ToolRows tools={TOOLS} route={route} collapsed={collapsed} />
        </nav>

        {collapsed ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="border-line-strong/60 mt-1 min-h-0 flex-1 scrollbar-thin space-y-0.5 overflow-y-auto border-t px-2 pt-3 pb-3">
              {active.slice(0, RAIL_RUNS).map((r, i) => (
                <RailRun key={r.id} run={r} active={isOpen(r.id)} reveal={reveal(i)} />
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
            {snoozed.length || settledTotal ? (
              <div className="flex shrink-0 flex-col items-center gap-0.5 pb-2">
                {snoozed.length ? (
                  <button
                    type="button"
                    onClick={openSnoozed}
                    onMouseEnter={snoozedTip.show}
                    onMouseLeave={snoozedTip.hide}
                    className={cn(SHELF_BUTTON, 'hover:text-brand-strong')}
                  >
                    <SnoozedIcon aria-hidden className="size-3.5" />
                    {snoozed.length}
                    <RailTip at={snoozedTip.at}>Snoozed threads</RailTip>
                  </button>
                ) : null}
                {settledTotal ? (
                  <button
                    type="button"
                    onClick={openSettled}
                    onMouseEnter={settledTip.show}
                    onMouseLeave={settledTip.hide}
                    className={cn(SHELF_BUTTON, 'hover:text-ok')}
                  >
                    <DoubleCheckIcon aria-hidden className="size-3.5" />
                    {settledTotal}
                    <RailTip at={settledTip.at}>Settled threads</RailTip>
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : (
          <div
            ref={scroller}
            className={cn('min-h-0 flex-1 overflow-y-auto', CONTENT_INSET, fades)}
          >
            <div className="flex min-h-full flex-col pt-2 pb-3">
              {!list ? (
                <div className={cn('space-y-4 pt-3', CONTENT_INSET)}>
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
                  ))}
                </div>
              ) : null}
              {group(shown).map(([label, list], index) => (
                <div key={label} className={index ? GROUP_GAP : undefined}>
                  <div className={cn('text-faint mb-1 text-[12px] font-medium', CONTENT_INSET)}>
                    {label}
                  </div>
                  <div className="space-y-0.5">
                    {list.map((r) => (
                      <RunItem
                        key={r.id}
                        run={r}
                        active={isOpen(r.id)}
                        reveal={reveal(shown.indexOf(r))}
                      />
                    ))}
                  </div>
                </div>
              ))}
              {!showAll && active.length > RECENT_LIMIT ? (
                <button
                  type="button"
                  onClick={() => setShowAll(true)}
                  className={cn(
                    'text-brand-strong hover:bg-canvas mt-1 h-9 w-full rounded-full text-left text-[12.5px] font-medium',
                    CONTENT_INSET,
                  )}
                >
                  Show all {active.length} threads
                </button>
              ) : null}
              {list && !active.length ? (
                <div className={cn('text-faint py-3 text-[12.5px]', CONTENT_INSET)}>
                  {settledTotal
                    ? 'Everything is settled. Start a new thread with a case number or a question.'
                    : 'Your threads appear here. Start one with a case number or a question.'}
                </div>
              ) : null}
              {snoozed.length || settledTotal ? (
                <div className="mt-auto space-y-1 pt-4">
                  {snoozed.length ? (
                    <Shelf
                      label="Snoozed"
                      runs={snoozed}
                      total={snoozed.length}
                      open={snoozedOpen}
                      onToggle={() => setSnoozedOpen((v) => !v)}
                      isOpen={isOpen}
                    />
                  ) : null}
                  {settledTotal ? (
                    <Shelf
                      label="Settled"
                      runs={settled}
                      total={settledTotal}
                      open={settledOpen}
                      onToggle={() => toggleSettled()}
                      onLoadMore={showMoreSettled}
                      settled
                      isOpen={isOpen}
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        )}

        {collapsed ? (
          <div className="border-line-strong/60 flex h-16 shrink-0 items-center justify-center border-t">
            {account ? (
              <AccountButton account={account} collapsed active={onSettings} />
            ) : (
              <Skeleton className="size-8 rounded-full" />
            )}
          </div>
        ) : (
          <div
            className={cn(
              'border-line-strong/60 flex h-16 shrink-0 items-center gap-1 border-t',
              FOOTER_INSET,
            )}
          >
            {account ? (
              <AccountButton account={account} collapsed={false} active={onSettings} />
            ) : (
              <span className={cn('flex h-11 min-w-0 flex-1 items-center gap-2.5', ACCOUNT_INSET)}>
                <Skeleton className="size-8 rounded-full" />
                <span className="space-y-1.5">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-2.5 w-24" />
                </span>
              </span>
            )}
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
