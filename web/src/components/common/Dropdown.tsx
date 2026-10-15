import {
  Check as CheckIcon,
  CaretDown as ChevronDownIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/cn'
import { useActiveIntoView, useClickOutside } from '@/lib/hooks'

export interface DropdownOption {
  value: string
  label: string
  hint?: string
  icon?: ReactNode
}

type Variant = 'chip' | 'field' | 'plain'

const SEARCH_MIN_OPTIONS = 10
const MENU_FLIP_SPACE = 300
const MENU_GAP = 4
const MENU_MIN_WIDTH = 180

const TRIGGER: Record<Variant, string> = {
  chip: 'h-7 rounded-full bg-brand-chip px-2.5 text-[12px] font-medium text-brand-strong hover:bg-brand hover:text-white',
  field:
    'h-9 w-full rounded-full border border-line-strong bg-white px-3.5 text-[13px] text-fg hover:border-brand',
  plain: 'h-8 rounded-full bg-raised px-3 text-[12px] font-medium text-text hover:bg-line',
}

export function Dropdown({
  value,
  onChange,
  options,
  placeholder = 'Select',
  variant = 'field',
  className,
  prefix,
  searchable,
  fluid,
}: {
  value: string
  onChange: (value: string) => void
  options: DropdownOption[]
  placeholder?: string
  variant?: Variant
  className?: string
  prefix?: ReactNode
  searchable?: boolean
  fluid?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [pos, setPos] = useState<{ left: number; top: number; minWidth: number; up: boolean }>()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const current = options.find((o) => o.value === value)
  const showSearch = searchable ?? options.length > SEARCH_MIN_OPTIONS
  const shown = query
    ? options.filter((o) =>
        `${o.label} ${o.hint ?? ''}`.toLowerCase().includes(query.toLowerCase()),
      )
    : options

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return

    const r = triggerRef.current.getBoundingClientRect()
    const up = r.bottom + MENU_FLIP_SPACE > window.innerHeight && r.top > MENU_FLIP_SPACE
    setPos({
      left: r.left,
      top: up ? r.top - MENU_GAP : r.bottom + MENU_GAP,
      minWidth: r.width,
      up,
    })
    setActive(
      Math.max(
        0,
        options.findIndex((o) => o.value === value),
      ),
    )
  }, [open])

  useClickOutside([menuRef, triggerRef], () => setOpen(false), open)

  useEffect(() => {
    if (!open) return

    const onScroll = (e: Event) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onResize = () => setOpen(false)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
    }
  }, [open])

  useActiveIntoView(menuRef, active)

  const pick = (o: DropdownOption) => {
    onChange(o.value)
    setOpen(false)
    setQuery('')
    triggerRef.current?.focus()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (['ArrowDown', 'Enter', ' '].includes(e.key)) {
        e.preventDefault()
        setOpen(true)
      }
      return
    }

    if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(shown.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter' && shown[active]) {
      e.preventDefault()
      pick(shown[active])
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(!open)}
        onKeyDown={onKeyDown}
        className={cn(
          'inline-flex items-center gap-1.5 text-left transition-colors outline-none',
          fluid ? 'min-w-0 shrink' : 'shrink-0',
          TRIGGER[variant],
          open && variant === 'chip' && 'bg-brand text-white',
          className,
        )}
      >
        {prefix ? <span className="shrink-0">{prefix}</span> : null}
        {current?.icon ? <span className="flex shrink-0 items-center">{current.icon}</span> : null}
        <span
          className={cn('min-w-0 flex-1 truncate', !current && variant === 'field' && 'text-faint')}
        >
          {current?.label ?? placeholder}
        </span>
        <ChevronDownIcon
          className={cn('size-3.5 shrink-0 opacity-70 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && pos
        ? createPortal(
            <div
              ref={menuRef}
              onKeyDown={onKeyDown}
              style={{
                left: pos.left,
                top: pos.up ? undefined : pos.top,
                bottom: pos.up ? window.innerHeight - pos.top : undefined,
                minWidth: Math.max(pos.minWidth, MENU_MIN_WIDTH),
              }}
              className="border-line-strong/70 animate-pop fixed z-[200] max-w-[360px] overflow-hidden rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
            >
              {showSearch ? (
                <div className="border-line-strong mb-1 flex h-8 items-center gap-1.5 rounded-full border bg-white px-3">
                  <MagnifyingGlassIcon className="text-faint size-3.5" />
                  <input
                    autoFocus
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value)
                      setActive(0)
                    }}
                    placeholder="Search"
                    className="placeholder:text-faint w-full bg-transparent text-[12px] outline-none"
                  />
                </div>
              ) : null}
              <div className="max-h-[280px] scrollbar-thin overflow-y-auto">
                {shown.map((o, i) => (
                  <button
                    key={o.value}
                    type="button"
                    data-index={i}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => pick(o)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-full px-3 py-1.5 text-left text-[12.5px]',
                      i === active ? 'bg-brand-soft text-brand-strong' : 'text-fg',
                    )}
                  >
                    {o.icon ? <span className="flex shrink-0 items-center">{o.icon}</span> : null}
                    <span className="shrink-0">{o.label}</span>
                    <span className="text-faint min-w-0 flex-1 truncate text-right text-[11px]">
                      {o.hint}
                    </span>
                    <CheckIcon
                      className={cn(
                        'text-brand size-3.5 shrink-0',
                        o.value !== value && 'invisible',
                      )}
                    />
                  </button>
                ))}
                {!shown.length ? (
                  <div className="text-faint px-2.5 py-2 text-[12px]">No matches</div>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
