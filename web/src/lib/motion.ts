import {
  type CSSProperties,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'

const REVEAL_LIMIT = 8
const REVEAL_WINDOW_MS = 700
const ACTIVE_SELECTOR = '[data-active]'
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  return window.matchMedia(REDUCED_MOTION).matches
}

export type Reveal = { className: string; style: CSSProperties } | undefined

export function useFirstLoadReveal(loading: boolean): (index: number) => Reveal {
  const [revealing, setRevealing] = useState(loading)

  useEffect(() => {
    if (loading || !revealing) return
    const timer = setTimeout(() => setRevealing(false), REVEAL_WINDOW_MS)
    return () => clearTimeout(timer)
  }, [loading, revealing])

  return (index) =>
    revealing && !loading
      ? {
          className: 'animate-reveal',
          style: { '--reveal-index': Math.min(index, REVEAL_LIMIT) } as CSSProperties,
        }
      : undefined
}

type Box = { x: number; y: number; width: number; height: number }

export type Indicator = (Box & { moving: boolean }) | undefined

function sameBox(a: Box, b: Box): boolean {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
}

export function useSlidingIndicator(
  container: RefObject<HTMLElement | null>,
  activeKey: string,
  layoutKey = '',
): Indicator {
  const [indicator, setIndicator] = useState<Indicator>()
  const layout = useRef(layoutKey)

  useLayoutEffect(() => {
    const root = container.current
    if (!root) return

    const measure = (moving: boolean) => {
      const active = root.querySelector<HTMLElement>(ACTIVE_SELECTOR)
      setIndicator((prev) => {
        if (!active) return undefined

        const next = {
          x: active.offsetLeft,
          y: active.offsetTop,
          width: active.offsetWidth,
          height: active.offsetHeight,
        }
        if (prev && sameBox(prev, next)) return prev
        return { ...next, moving: moving && prev !== undefined }
      })
    }

    measure(layout.current === layoutKey)
    layout.current = layoutKey
    const resize = new ResizeObserver(() => measure(false))
    resize.observe(root)
    return () => resize.disconnect()
  }, [container, activeKey, layoutKey])

  return indicator
}

export function indicatorStyle(indicator: Box): CSSProperties {
  return {
    transform: `translate(${indicator.x}px, ${indicator.y}px)`,
    width: indicator.width,
    height: indicator.height,
  }
}
