import { type RefObject, useCallback, useEffect, useLayoutEffect, useRef } from 'react'

const FOLLOW_BOTTOM_PX = 80
const USER_SCROLL_MS = 600
const USER_SCROLL_EVENTS = ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const

export function useThreadScroll(
  scrollRef: RefObject<HTMLDivElement | null>,
  loadOlder: (until?: number) => Promise<void>,
  start: number | undefined,
  ready: boolean,
  browsing: boolean,
) {
  const followBottom = useRef(true)
  const restoreHeight = useRef<number | undefined>(undefined)

  const older = useCallback(
    (until?: number) => {
      restoreHeight.current = scrollRef.current?.parentElement?.scrollHeight
      return loadOlder(until)
    },
    [loadOlder],
  )

  useLayoutEffect(() => {
    const scroller = scrollRef.current?.parentElement
    if (restoreHeight.current === undefined || !scroller) return
    scroller.scrollTop += scroller.scrollHeight - restoreHeight.current
    restoreHeight.current = undefined
  }, [start])

  useEffect(() => {
    const content = scrollRef.current
    const scroller = content?.parentElement
    if (!content || !scroller) return

    let userScrolledAt = 0
    const pinToBottom = () => {
      if (followBottom.current) scroller.scrollTop = scroller.scrollHeight
    }
    const markUser = () => {
      userScrolledAt = Date.now()
    }
    const onScroll = () => {
      const fromBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
      if (fromBottom < FOLLOW_BOTTOM_PX) followBottom.current = true
      else if (Date.now() - userScrolledAt < USER_SCROLL_MS) followBottom.current = false
    }

    followBottom.current = true
    const contentGrowth = new ResizeObserver(pinToBottom)
    contentGrowth.observe(content)
    scroller.addEventListener('scroll', onScroll, { passive: true })
    for (const name of USER_SCROLL_EVENTS)
      scroller.addEventListener(name, markUser, { passive: true })

    pinToBottom()

    return () => {
      contentGrowth.disconnect()
      scroller.removeEventListener('scroll', onScroll)
      for (const name of USER_SCROLL_EVENTS) scroller.removeEventListener(name, markUser)
    }
  }, [ready, browsing])

  return { followBottom, older }
}
