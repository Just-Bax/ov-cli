import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'
import type { OutlineMark } from '@shared/types.ts'
import { Markdown } from '@/components/common/ui'
import { cn } from '@/lib/cn'

const MIN_MARKS = 2
const MARK_SPACING_PX = 8
const MAX_RAIL_PX = 640
const RAIL_PADDING_PX = 48
const HIT_PX = 6
const LABEL_CHARS = 140
const REPLY_CHARS = 220
const FISHEYE = ['w-4', 'w-3', 'w-2.5']
const RESTING = 'w-2'

type Mark = {
  el?: HTMLElement
  start: number
  label: string
  reply: string
  top: number
  height: number
}

function collect(content: HTMLElement): Mark[] {
  const origin = content.getBoundingClientRect().top
  const replies = new Map(
    [...content.querySelectorAll<HTMLElement>('[data-mark="agent"]')].map((el) => [
      el.dataset.start,
      el.dataset.label ?? '',
    ]),
  )
  return [...content.querySelectorAll<HTMLElement>('[data-mark="user"]')].map((el) => {
    const box = el.getBoundingClientRect()
    return {
      el,
      start: Number(el.dataset.start),
      label: (el.dataset.label ?? '').slice(0, LABEL_CHARS),
      reply: (replies.get(el.dataset.start) ?? '').slice(0, REPLY_CHARS),
      top: box.top - origin,
      height: box.height,
    }
  })
}

function fromOutline(outline: OutlineMark[]): Mark[] {
  const replies = new Map(outline.filter((m) => m.kind === 'agent').map((m) => [m.start, m.label]))
  return outline
    .filter((m) => m.kind === 'user')
    .map((m) => ({
      start: m.start,
      label: m.label.slice(0, LABEL_CHARS),
      reply: (replies.get(m.start) ?? '').slice(0, REPLY_CHARS),
      top: -1,
      height: 0,
    }))
}

function inView(mark: Mark, view: { top: number; bottom: number }): boolean {
  return mark.el !== undefined && mark.top < view.bottom && mark.top + mark.height > view.top
}

function currentIndex(marks: Mark[], view: { top: number; bottom: number }): number {
  const visible = marks.findIndex((m) => inView(m, view))
  if (visible >= 0) return visible
  return marks.findLastIndex((m) => m.el !== undefined && m.top <= view.top)
}

function offset(index: number, count: number, tall: number): number {
  return count <= 1 ? 0 : (index / (count - 1)) * tall
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
  const frame = useRef<number | undefined>(undefined)
  const strip = useRef<HTMLButtonElement>(null)

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

  const all = [...fromOutline(outline), ...marks]
  if (all.length < MIN_MARKS || !view.height) return null

  const tall = Math.min(
    (all.length - 1) * MARK_SPACING_PX,
    MAX_RAIL_PX,
    view.height - RAIL_PADDING_PX * 2,
  )
  const current = currentIndex(all, view)
  const focus = hover ?? current

  const pointed = (clientY: number) => {
    const box = strip.current?.getBoundingClientRect()
    if (!box) return undefined
    const progress = Math.max(0, Math.min(1, (clientY - box.top - HIT_PX) / tall))
    return Math.round(progress * (all.length - 1))
  }

  const jump = async (m: Mark) => {
    onJump()
    if (m.el) return m.el.scrollIntoView({ block: 'start', behavior: 'smooth' })

    await onLoadUntil(m.start)
    await nextFrame()
    await nextFrame()
    contentRef.current
      ?.querySelector<HTMLElement>(`[data-mark="user"][data-start="${m.start}"]`)
      ?.scrollIntoView({ block: 'start' })
  }

  const step = (by: number) => {
    const next = Math.max(0, Math.min(all.length - 1, (focus < 0 ? all.length : focus) + by))
    setHover(next)
  }

  const shown = hover === undefined ? undefined : all[hover]

  return (
    <div className="pointer-events-none sticky top-0 z-20 h-0">
      <button
        ref={strip}
        type="button"
        aria-label={shown ? `Go to your message: ${shown.label}` : 'Your messages in this thread'}
        className="pointer-events-auto absolute right-2 w-7 cursor-pointer"
        style={{ top: (view.height - tall) / 2 - HIT_PX, height: tall + HIT_PX * 2 }}
        onMouseMove={(e) => setHover(pointed(e.clientY))}
        onMouseLeave={() => setHover(undefined)}
        onBlur={() => setHover(undefined)}
        onWheel={(e) => contentRef.current?.parentElement?.scrollBy({ top: e.deltaY })}
        onClick={(e) => {
          const index = e.detail ? pointed(e.clientY) : hover
          if (index !== undefined) void jump(all[index])
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            step(e.key === 'ArrowDown' ? 1 : -1)
          }
        }}
      >
        {all.map((m, i) => {
          const distance = focus < 0 ? FISHEYE.length : Math.abs(i - focus)
          return (
            <span
              key={m.start}
              className={cn(
                'absolute right-1.5 h-[2px] -translate-y-1/2 rounded-full transition-all duration-150',
                hover !== undefined ? (FISHEYE[distance] ?? RESTING) : RESTING,
                i === hover ? 'bg-brand' : inView(m, view) ? 'bg-brand-strong' : 'bg-line-strong',
              )}
              style={{ top: HIT_PX + offset(i, all.length, tall) }}
            />
          )
        })}
      </button>
      {shown ? (
        <div
          className="border-line text-text pointer-events-none absolute right-10 w-[300px] -translate-y-1/2 rounded-2xl border bg-white px-3 py-2 shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
          style={{ top: (view.height - tall) / 2 + offset(hover ?? 0, all.length, tall) }}
        >
          <div className="text-fg truncate text-[12.5px] font-medium">{shown.label}</div>
          {shown.reply ? (
            <div className="text-muted mt-1 line-clamp-2 text-[12px]">
              <Markdown text={shown.reply} className="md-compact" />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
