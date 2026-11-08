import { useEffect, useState } from 'react'
import type { SidebarAccount } from '@/components/layout/AccountMenu'
import { OPEN_PALETTE, TOGGLE_SIDEBAR } from '@/components/layout/CommandPalette'
import { cn } from '@/lib/cn'
import { useWindowEvent } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { useFirstLoadReveal } from '@/lib/motion'
import type { Route } from '@/lib/route'
import { useRuns } from '@/lib/runs'
import { useRailTip } from './RailTip'
import { RailThreads } from './RailThreads'
import { SidebarFooter } from './SidebarFooter'
import { SidebarHeader } from './SidebarHeader'
import { SidebarNav } from './SidebarNav'
import { SidebarThreads } from './SidebarThreads'

const SETTLED_OPEN_KEY = 'ov-agent.settled-open'
const COLLAPSED_KEY = 'ov-agent.sidebar-collapsed'
const DOCK_QUERY = '(min-width: 1200px)'
const EXPANDED_WIDTH = 'w-[332px]'

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

export function Sidebar({ route, account }: { route: Route; account?: SidebarAccount }) {
  const list = useRuns()
  const [showAll, setShowAll] = useState(false)
  const [pinnedCollapsed, setCollapsed] = useState(storedCollapsed)
  const [drawer, setDrawer] = useState(false)
  const [snoozedOpen, setSnoozedOpen] = useState(false)
  const [settledOpen, setSettledOpen] = useState(
    () => localStorage.getItem(SETTLED_OPEN_KEY) === '1',
  )

  const toggleTip = useRailTip()
  const docked = useDocked()
  const collapsed = docked ? pinnedCollapsed : !drawer
  const overlay = !docked && drawer
  const routeKey = JSON.stringify(route)

  useEffect(() => setDrawer(false), [routeKey, docked])
  useLayer(() => setDrawer(false), overlay)

  const onSettings = route.page === 'settings'
  const isOpen = (id: string) => route.page === 'thread' && route.id === id
  const reveal = useFirstLoadReveal(!list)

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
          'border-line-strong/60 z-20 flex shrink-0 flex-col border-r bg-white transition-[width] duration-(--duration-medium) ease-out',
          overlay
            ? cn(
                'animate-slide-in fixed inset-y-0 left-0 z-50 shadow-[0_12px_40px_rgba(38,50,56,0.22)]',
                EXPANDED_WIDTH,
              )
            : 'relative',
          !overlay && (collapsed ? 'w-[72px]' : EXPANDED_WIDTH),
        )}
      >
        <SidebarHeader
          collapsed={collapsed}
          toggleTip={toggleTip}
          onToggle={toggle}
          onSearch={openPalette}
        />
        <SidebarNav route={route} collapsed={collapsed} onSearch={openPalette} />

        {collapsed ? (
          <RailThreads
            list={list}
            reveal={reveal}
            isOpen={isOpen}
            onShowAll={toggle}
            onOpenSnoozed={openSnoozed}
            onOpenSettled={openSettled}
          />
        ) : (
          <SidebarThreads
            list={list}
            showAll={showAll}
            snoozedOpen={snoozedOpen}
            settledOpen={settledOpen}
            reveal={reveal}
            isOpen={isOpen}
            onShowAll={() => setShowAll(true)}
            onToggleSnoozed={() => setSnoozedOpen((v) => !v)}
            onToggleSettled={() => toggleSettled()}
          />
        )}

        <SidebarFooter account={account} collapsed={collapsed} onSettings={onSettings} />
      </aside>
    </>
  )
}
