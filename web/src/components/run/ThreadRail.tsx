import { CaretDown as ChevronDownIcon, CaretUp as ChevronUpIcon } from '@phosphor-icons/react'
import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'
import type { OutlineMark } from '@shared/types.ts'
import { Markdown } from '@/components/common/ui'
import { cn } from '@/lib/cn'

const MIN_MARKS = 4
const MARK_GAP_PX = 9
const MIN_GAP_PX = 4
const ARROW_PX = 30
const WHEEL_STEP = 3
const RAIL_PADDING_PX = 24
const LABEL_CHARS = 140

type Mark = {
  el?: HTMLElement
  kind: string
  start: number
  label: string
  top: number
  height: number
}

function collect(content: HTMLElement): Mark[] {
  const origin = content.getBoundingClientRect().top
  return [...content.querySelectorAll<HTMLElement>('[data-mark]')].map((el) => {
    const box = el.getBoundingClientRect()
    return {
      el,
      kind: el.dataset.mark ?? '',
      start: Number(el.dataset.start),
      label: (el.dataset.label ?? '').slice(0, LABEL_CHARS),
      top: box.top - origin,
      height: box.height,
    }
  })
}

function inView(mark: Mark, view: { top: number; bottom: number }): boolean {
  return mark.el !== undefined && mark.top < view.bottom && mark.top + mark.height > view.top
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

export function ThreadRail({
  contentRef,
  version,
  outline,
  onLoadUntil,
  onJump,
}: {
  contentRef: RefObject<HTMLDivElement | null>
  version: unknown
  outline: OutlineMark[]
  onLoadUntil: (start: number) => Promise<void>
  onJump: () => void
}) {
  const [marks, setMarks] = useState<Mark[]>([])
  const [view, setView] = useState({ top: 0, bottom: 0, height: 0 })
  const [hover, setHover] = useState<number>()
  const [first, setFirst] = useState<number>()
  const frame = useRef<number | undefined>(undefined)

  const measure = useCallback(() => {
    frame.current = undefined
    const content = contentRef.current
    const scroller = content?.parentElement
    if (!content || !scroller) return

    setMarks(collect(content))
    const top = scroller.getBoundingClientRect().top - content.getBoundingClientRect().top
    setView({ top, bottom: top + scroller.clientHeight, height: scroller.clientHeight })
  }, [contentRef])

  const schedule = useCallback(() => {
    frame.current ??= requestAnimationFrame(measure)
  }, [measure])

  useEffect(schedule, [schedule, version])

  useEffect(() => {
    const scroller = contentRef.current?.parentElement
    if (!scroller) return
    const follow = () => setFirst(undefined)
    scroller.addEventListener('scroll', follow, { passive: true })
    return () => scroller.removeEventListener('scroll', follow)
  }, [contentRef])

  useEffect(() => {
    const scroller = contentRef.current?.parentElement
    if (!scroller) return

    const resize = new ResizeObserver(schedule)
    resize.observe(scroller)
    scroller.addEventListener('scroll', schedule, { passive: true })
    return () => {
      resize.disconnect()
      scroller.removeEventListener('scroll', schedule)
      if (frame.current !== undefined) cancelAnimationFrame(frame.current)
      frame.current = undefined
    }
  }, [contentRef, schedule])

  const all: Mark[] = [
    ...outline.map((m) => ({ ...m, label: m.label.slice(0, LABEL_CHARS), top: -1, height: 0 })),
    ...marks,
  ]
  if (all.length < MIN_MARKS || !view.height) return null

  const room = view.height - RAIL_PADDING_PX * 2
  const overflow = all.length * MIN_GAP_PX > room
  const gap = overflow ? MARK_GAP_PX : Math.min(MARK_GAP_PX, room / all.length)
  const capacity = overflow ? Math.max(1, Math.floor((room - ARROW_PX * 2) / gap)) : all.length
  const last = all.length - capacity
  const visibleAt = all.findIndex((m) => inView(m, view))
  const centered = visibleAt < 0 ? last : visibleAt - Math.floor(capacity / 2)
  const start = Math.max(0, Math.min(last, first ?? centered))
  const shown = all.slice(start, start + capacity)
  const above = overflow && start > 0
  const below = overflow && start < last
  const lead = overflow ? ARROW_PX : 0
  const tall = shown.length * gap + lead * 2
  const move = (by: number) => setFirst(Math.max(0, Math.min(last, start + by)))

  const jump = async (m: Mark) => {
    onJump()
    if (m.el) return m.el.scrollIntoView({ block: 'start', behavior: 'smooth' })

    await onLoadUntil(m.start)
    await nextFrame()
    await nextFrame()
    contentRef.current
      ?.querySelector<HTMLElement>(`[data-mark="${m.kind}"][data-start="${m.start}"]`)
      ?.scrollIntoView({ block: 'start' })
  }

  return (
    <div className="pointer-events-none sticky top-0 z-20 h-0">
      <div
        className="pointer-events-auto absolute right-2 flex w-6 flex-col items-center"
        style={{ top: (view.height - tall) / 2, height: tall }}
        onMouseLeave={() => setHover(undefined)}
        onWheel={(e) => overflow && move(Math.sign(e.deltaY) * WHEEL_STEP)}
      >
        {overflow ? <RailArrow up hidden={!above} onClick={() => move(-(capacity - 1))} /> : null}
        {shown.map((m, i) => {
          const visible = inView(m, view)
          return (
            <button
              key={`${m.kind}:${m.start}`}
              type="button"
              aria-label={`Go to ${m.kind === 'user' ? 'your message' : 'reply'}`}
              onMouseEnter={() => setHover(i)}
              onClick={() => void jump(m)}
              className="flex w-full shrink-0 items-center justify-center"
              style={{ height: gap }}
            >
              <span
                className={cn(
                  'h-[2px] rounded-full transition-all',
                  m.kind === 'user' ? 'w-3.5' : 'w-2.5',
                  hover === i
                    ? 'bg-brand w-4'
                    : visible
                      ? m.kind === 'user'
                        ? 'bg-brand-strong'
                        : 'bg-muted'
                      : m.kind === 'user'
                        ? 'bg-brand/45'
                        : 'bg-line-strong',
                )}
              />
            </button>
          )
        })}
        {overflow ? <RailArrow hidden={!below} onClick={() => move(capacity - 1)} /> : null}
        {hover !== undefined && shown[hover]?.label ? (
          <div
            className="border-line text-text pointer-events-none absolute right-7 w-[280px] -translate-y-1/2 rounded-2xl border bg-white px-3 py-2 shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
            style={{ top: lead + hover * gap + gap / 2 }}
          >
            <div className="text-faint mb-0.5 text-[10.5px] font-medium">
              {shown[hover].kind === 'user' ? 'You' : 'Agent'}
            </div>
            <div className="line-clamp-3">
              <Markdown text={shown[hover].label} className="md-compact" />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function RailArrow({
  up,
  hidden,
  onClick,
}: {
  up?: boolean
  hidden: boolean
  onClick: () => void
}) {
  const Icon = up ? ChevronUpIcon : ChevronDownIcon

  return (
    <div className="flex shrink-0 items-center justify-center" style={{ height: ARROW_PX }}>
      {hidden ? null : (
        <button
          type="button"
          aria-label={up ? 'Earlier messages' : 'Later messages'}
          onClick={onClick}
          className="bg-raised text-muted hover:bg-brand-soft hover:text-brand-strong animate-fade-in flex size-6 items-center justify-center rounded-full transition-colors"
        >
          <Icon className="size-3.5" />
        </button>
      )}
    </div>
  )
}
