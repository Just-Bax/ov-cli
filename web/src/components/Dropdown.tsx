import { Check, ChevronDown, Search } from 'lucide-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/cn'

export interface Option {
  value: string
  label: string
  hint?: string
}

type Variant = 'chip' | 'field' | 'plain'

const TRIGGER: Record<Variant, string> = {
  chip: 'h-7 rounded-full bg-brand-chip px-2.5 text-[12px] font-medium text-brand-strong hover:bg-brand hover:text-white',
  field:
    'h-9 w-full rounded-full border border-line-strong bg-white px-3.5 text-[13px] text-fg hover:border-brand',
  plain: 'h-8 rounded-full bg-raised px-3 text-[12px] font-medium text-text hover:bg-line',
}

/** OneVizion-style dropdown: chip or field trigger, floating menu, check on the selected item. */
export function Dropdown({
  value,
  onChange,
  options,
  placeholder = 'Select',
  variant = 'field',
  className,
  prefix,
  searchable,
}: {
  value: string
  onChange: (value: string) => void
  options: Option[]
  placeholder?: string
  variant?: Variant
  className?: string
  prefix?: ReactNode
  searchable?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [pos, setPos] = useState<{ left: number; top: number; minWidth: number; up: boolean }>()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const current = options.find((o) => o.value === value)
  const showSearch = searchable ?? options.length > 10
  const shown = query
    ? options.filter((o) =>
        `${o.label} ${o.hint ?? ''}`.toLowerCase().includes(query.toLowerCase()),
      )
    : options

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return
    const r = triggerRef.current.getBoundingClientRect()
    const up = r.bottom + 300 > window.innerHeight && r.top > 300
    setPos({ left: r.left, top: up ? r.top - 4 : r.bottom + 4, minWidth: r.width, up })
    setActive(
      Math.max(
        0,
        options.findIndex((o) => o.value === value),
      ),
    )
  }, [open])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (
        !menuRef.current?.contains(e.target as Node) &&
        !triggerRef.current?.contains(e.target as Node)
      )
        setOpen(false)
    }
    const onScroll = (e: Event) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', () => setOpen(false), { once: true })
    return () => {
      document.removeEventListener('mousedown', close)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open])

  useEffect(() => {
    menuRef.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const pick = (o: Option) => {
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
          'inline-flex shrink-0 items-center gap-1.5 text-left transition-colors outline-none',
          TRIGGER[variant],
          open && variant === 'chip' && 'bg-brand text-white',
          className,
        )}
      >
        {prefix}
        <span
          className={cn('min-w-0 flex-1 truncate', !current && variant === 'field' && 'text-faint')}
        >
          {current?.label ?? placeholder}
        </span>
        <ChevronDown
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
                minWidth: Math.max(pos.minWidth, 180),
              }}
              className="border-line-strong/70 fixed z-50 max-w-[360px] overflow-hidden rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
            >
              {showSearch ? (
                <div className="border-line-strong mb-1 flex h-8 items-center gap-1.5 rounded-full border bg-white px-3">
                  <Search className="text-faint size-3.5" />
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
                      'flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12.5px]',
                      i === active ? 'bg-brand-soft text-brand-strong' : 'text-fg',
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate">{o.label}</span>
                    {o.hint ? (
                      <span className="text-faint shrink-0 text-[11px]">{o.hint}</span>
                    ) : null}
                    <Check
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
