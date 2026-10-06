import { type RefObject, useCallback, useEffect, useState } from 'react'
import { cn } from '@/lib/cn'

const MIN_MARKS = 4
const MARK_GAP_PX = 9
const MIN_GAP_PX = 3
const RAIL_PADDING_PX = 24
const LABEL_CHARS = 140

type Mark = { el: HTMLElement; kind: string; label: string; top: number; height: number }

function collect(content: HTMLElement): Mark[] {
  const origin = content.getBoundingClientRect().top
  return [...content.querySelectorAll<HTMLElement>('[data-mark]')].map((el) => {
    const box = el.getBoundingClientRect()
    return {
      el,
      kind: el.dataset.mark ?? '',
      label: (el.dataset.label ?? '').slice(0, LABEL_CHARS),
      top: box.top - origin,
      height: box.height,
    }
  })
}

export function ThreadRail({
  contentRef,
  version,
  onJump,
}: {
  contentRef: RefObject<HTMLDivElement | null>
  version: unknown
  onJump: () => void
}) {
  const [marks, setMarks] = useState<Mark[]>([])
  const [view, setView] = useState({ top: 0, bottom: 0, height: 0 })
  const [hover, setHover] = useState<number>()

  const measure = useCallback(() => {
    const content = contentRef.current
    const scroller = content?.parentElement
    if (!content || !scroller) return

    setMarks(collect(content))
    const top = scroller.getBoundingClientRect().top - content.getBoundingClientRect().top
    setView({ top, bottom: top + scroller.clientHeight, height: scroller.clientHeight })
  }, [contentRef])

  useEffect(measure, [measure, version])

  useEffect(() => {
    const scroller = contentRef.current?.parentElement
    if (!scroller) return

    const resize = new ResizeObserver(measure)
    resize.observe(scroller)
    scroller.addEventListener('scroll', measure, { passive: true })
    return () => {
      resize.disconnect()
      scroller.removeEventListener('scroll', measure)
    }
  }, [contentRef, measure])

  if (marks.length < MIN_MARKS || !view.height) return null

  const room = view.height - RAIL_PADDING_PX * 2
  const gap = Math.max(MIN_GAP_PX, Math.min(MARK_GAP_PX, room / marks.length))
  const shown = marks.slice(-Math.floor(room / gap))
  const tall = shown.length * gap

  return (
    <div className="pointer-events-none sticky top-0 z-20 h-0">
      <div
        className="pointer-events-auto absolute right-2 flex w-6 flex-col items-center"
        style={{ top: (view.height - tall) / 2, height: tall }}
        onMouseLeave={() => setHover(undefined)}
      >
        {shown.map((m, i) => {
          const visible = m.top < view.bottom && m.top + m.height > view.top
          return (
            <button
              key={i}
              type="button"
              aria-label={`Go to ${m.kind === 'user' ? 'your message' : 'reply'}`}
              onMouseEnter={() => setHover(i)}
              onClick={() => {
                onJump()
                m.el.scrollIntoView({ block: 'start', behavior: 'smooth' })
              }}
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
        {hover !== undefined && shown[hover]?.label ? (
          <div
            className="border-line text-text pointer-events-none absolute right-7 w-[280px] -translate-y-1/2 rounded-2xl border bg-white px-3 py-2 text-[12px] leading-snug shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
            style={{ top: hover * gap + gap / 2 }}
          >
            <div className="text-faint mb-0.5 text-[10.5px] font-medium">
              {shown[hover].kind === 'user' ? 'You' : 'Agent'}
            </div>
            <div className="line-clamp-3">{shown[hover].label}</div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
