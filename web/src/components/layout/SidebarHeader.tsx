import { MagnifyingGlass as SearchIcon, SidebarSimple as SidebarIcon } from '@phosphor-icons/react'
import mark from '@/assets/ov-mark.svg'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { cn } from '@/lib/cn'
import { href } from '@/lib/route'
import { RailTip, type RailTipHandle } from './RailTip'
import { SEARCH_LABEL } from './SidebarNav'

const OPEN_SIDEBAR_LABEL = 'Open sidebar (Ctrl+B)'
const CLOSE_SIDEBAR_LABEL = 'Close sidebar (Ctrl+B)'
const HEADER_BUTTON =
  'text-faint hover:bg-canvas hover:text-brand-strong flex size-8 items-center justify-center rounded-full transition-colors'

export function SidebarHeader({
  collapsed,
  toggleTip,
  onToggle,
  onSearch,
}: {
  collapsed: boolean
  toggleTip: RailTipHandle
  onToggle: () => void
  onSearch: () => void
}) {
  return (
    <div
      className={cn(
        'flex h-16 shrink-0 items-center overflow-hidden',
        collapsed ? 'justify-center' : 'justify-between pr-3 pl-5',
      )}
    >
      {collapsed ? (
        <button
          type="button"
          onClick={onToggle}
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
              onClick={onSearch}
              aria-label="Search"
              title={SEARCH_LABEL}
              className={HEADER_BUTTON}
            >
              <SearchIcon className="size-[18px]" />
            </button>
            <button
              type="button"
              onClick={onToggle}
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
  )
}
