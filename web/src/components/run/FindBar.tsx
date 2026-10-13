import {
  CaretDown as ChevronDownIcon,
  CaretUp as ChevronUpIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type RefObject, useEffect, useRef, useState } from 'react'
import { reportError } from '@/components/Toasts'
import { Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useLayer } from '@/lib/layers'

const SEARCH_DELAY_MS = 200
const MATCH = 'ov-find'
const CURRENT = 'ov-find-current'

function textRanges(root: HTMLElement, query: string): Range[] {
  const wanted = query.toLocaleLowerCase()
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement?.closest('[data-find-skip]')
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  })
  const ranges: Range[] = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.textContent ?? '').toLocaleLowerCase()
    for (let at = text.indexOf(wanted); at >= 0; at = text.indexOf(wanted, at + wanted.length)) {
      const range = document.createRange()
      range.setStart(node, at)
      range.setEnd(node, at + wanted.length)
      ranges.push(range)
    }
  }
  return ranges
}

function paint(ranges: Range[], current: number) {
  CSS.highlights.set(MATCH, new Highlight(...ranges))
  const active = ranges[current]
  if (active) CSS.highlights.set(CURRENT, new Highlight(active))
  else CSS.highlights.delete(CURRENT)
}

function clear() {
  CSS.highlights.delete(MATCH)
  CSS.highlights.delete(CURRENT)
}

export function FindBar({
  runId,
  contentRef,
  start,
  version,
  onLoadUntil,
  onClose,
}: {
  runId: string
  contentRef: RefObject<HTMLDivElement | null>
  start: number
  version: number
  onLoadUntil: (index: number) => Promise<void>
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [ranges, setRanges] = useState<Range[]>([])
  const [current, setCurrent] = useState(0)
  const [searching, setSearching] = useState(false)
  const [none, setNone] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const startRef = useRef(start)
  startRef.current = start

  useLayer(onClose)

  useEffect(() => {
    input.current?.focus()
    return clear
  }, [])

  useEffect(() => {
    const wanted = query.trim()
    setNone(false)
    if (!wanted) {
      setRanges([])
      clear()
      return
    }

    let alive = true
    const timer = setTimeout(() => {
      setSearching(true)
      api
        .searchRun(runId, wanted)
        .then(async ({ items }) => {
          if (!alive) return
          setNone(!items.length)
          const first = items[0]
          if (first !== undefined && first < startRef.current) await onLoadUntil(first)
        })
        .catch(reportError)
        .finally(() => alive && setSearching(false))
    }, SEARCH_DELAY_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [query, runId, onLoadUntil])

  useEffect(() => {
    const root = contentRef.current
    const wanted = query.trim()
    if (!root || !wanted) return
    const found = textRanges(root, wanted)
    setRanges(found)
    setCurrent(found.length ? found.length - 1 : 0)
  }, [query, version, contentRef])

  useEffect(() => {
    if (!ranges.length) return clear()
    paint(ranges, current)
    ranges[current]?.startContainer.parentElement?.scrollIntoView({ block: 'center' })
  }, [ranges, current])

  const step = (by: number) => {
    if (ranges.length) setCurrent((c) => (c + by + ranges.length) % ranges.length)
  }

  return (
    <div
      data-find-skip
      className="border-line animate-pop absolute top-2 right-6 z-30 flex h-10 items-center gap-1 rounded-full border bg-white pr-1 pl-3 shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
    >
      <MagnifyingGlassIcon className="text-faint size-4 shrink-0" />
      <input
        ref={input}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            step(e.shiftKey ? 1 : -1)
          }
        }}
        placeholder="Find in thread"
        aria-label="Find in thread"
        className="placeholder:text-faint text-fg w-[220px] bg-transparent text-[13px] outline-none"
      />
      <span
        className={cn(
          'w-[64px] shrink-0 text-right text-[12px] tabular-nums',
          none && !searching ? 'text-danger' : 'text-muted',
        )}
      >
        {searching ? (
          <Spinner className="text-brand ml-auto size-3.5" />
        ) : !query.trim() ? null : ranges.length ? (
          `${current + 1} of ${ranges.length}`
        ) : (
          'No results'
        )}
      </span>
      <FindButton label="Previous match (Enter)" onClick={() => step(-1)} disabled={!ranges.length}>
        <ChevronUpIcon className="size-4" />
      </FindButton>
      <FindButton
        label="Next match (Shift+Enter)"
        onClick={() => step(1)}
        disabled={!ranges.length}
      >
        <ChevronDownIcon className="size-4" />
      </FindButton>
      <FindButton label="Close (Esc)" onClick={onClose}>
        <XMarkIcon className="size-4" />
      </FindButton>
    </div>
  )
}

function FindButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="text-muted hover:bg-raised hover:text-fg disabled:text-line-strong flex size-8 items-center justify-center rounded-full transition-colors"
    >
      {children}
    </button>
  )
}
