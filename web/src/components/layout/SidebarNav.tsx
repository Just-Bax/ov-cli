import {
  Heartbeat as HeartIcon,
  MagnifyingGlass as SearchIcon,
  MapTrifold as MapIcon,
  Plus as PlusIcon,
} from '@phosphor-icons/react'
import { useRef } from 'react'
import { type Icon, SlideIndicator } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { useSlidingIndicator } from '@/lib/motion'
import { href, type Route } from '@/lib/route'
import { RailTip, useRailTip } from './RailTip'

export const SEARCH_LABEL = 'Search (Ctrl+K)'

type NavTool = { route: Route; label: string; icon: Icon }

const TOOLS: NavTool[] = [
  { route: { page: 'map' }, label: 'Instance map', icon: MapIcon },
  { route: { page: 'health' }, label: 'Instance health', icon: HeartIcon },
]

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

export function SidebarNav({
  route,
  collapsed,
  onSearch,
}: {
  route: Route
  collapsed: boolean
  onSearch: () => void
}) {
  const nav = useRef<HTMLElement>(null)
  const navIndicator = useSlidingIndicator(nav, route.page, String(collapsed))

  return (
    <nav ref={nav} className="relative shrink-0 space-y-0.5 px-3 pb-2">
      <SlideIndicator indicator={navIndicator} className="bg-brand-soft rounded-full" />
      {collapsed ? (
        <NavRow
          icon={SearchIcon}
          label={SEARCH_LABEL}
          active={false}
          collapsed
          onClick={onSearch}
        />
      ) : null}
      <NavRow
        to={href({ page: 'home' })}
        icon={PlusIcon}
        label="New thread"
        active={route.page === 'home'}
        collapsed={collapsed}
      />
      {TOOLS.map((tool) => (
        <NavRow
          key={tool.label}
          to={href(tool.route)}
          icon={tool.icon}
          label={tool.label}
          active={route.page === tool.route.page}
          collapsed={collapsed}
        />
      ))}
    </nav>
  )
}
