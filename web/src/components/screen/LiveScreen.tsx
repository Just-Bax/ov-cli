import {
  ArrowLeft as ArrowLeftIcon,
  ArrowSquareOut as OpenIcon,
  Check as CheckIcon,
  Copy as CopyIcon,
  Globe as GlobeAltIcon,
  Lock as LockClosedIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react'
import { reportError } from '@/components/common/Toasts'
import { Shimmer, useCopy } from '@/components/common/ui'
import { cn } from '@/lib/cn'

export const SCREEN_BAR_PX = 52
const SCREEN_MARGIN_PX = 48
const MAX_SCREEN_WIDTH = 1280
const MAX_SCREEN_HEIGHT = 900
const BLANK_PAGE = 'about:blank'

const MODIFIER = { alt: 1, ctrl: 2, meta: 4, shift: 8 }
const BUTTON_NAMES = ['left', 'middle', 'right'] as const
const RESIZE_SETTLE_MS = 200

type Frame = { data: string; url: string; width: number; height: number }
export type FrameSize = { width: number; height: number }
type ScreenEvent = Record<string, unknown> & { type: string }
type SendScreen = (events: ScreenEvent[]) => Promise<{ open: boolean }>
type Phase = 'starting' | 'live' | 'gone'

type Address = { host: string; rest: string; secure: boolean; href?: string }

const BAR_ACTION =
  'text-muted hover:text-brand-strong flex size-6 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-white hover:shadow-[0_1px_2px_rgba(0,0,0,0.08)]'

function splitAddress(address: string): Address {
  const full = /^[a-z][a-z0-9+.-]*:/i.test(address) ? address : `https://${address}`
  if (!URL.canParse(full)) return { host: address, rest: '', secure: false }

  const url = new URL(full)

  return {
    host: url.host,
    rest: `${url.pathname === '/' ? '' : url.pathname}${url.search}${url.hash}`,
    secure: url.protocol === 'https:',
    href: url.protocol === 'http:' || url.protocol === 'https:' ? url.href : undefined,
  }
}

export function screenSize(): FrameSize {
  return {
    width: Math.min(MAX_SCREEN_WIDTH, window.innerWidth - SCREEN_MARGIN_PX),
    height: Math.min(MAX_SCREEN_HEIGHT, window.innerHeight - SCREEN_MARGIN_PX - SCREEN_BAR_PX),
  }
}

function modifiers(e: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) {
  return (
    (e.altKey ? MODIFIER.alt : 0) |
    (e.ctrlKey ? MODIFIER.ctrl : 0) |
    (e.metaKey ? MODIFIER.meta : 0) |
    (e.shiftKey ? MODIFIER.shift : 0)
  )
}

function useSender(deliver: SendScreen) {
  const pending = useRef<ScreenEvent[]>([])
  const busy = useRef(false)
  const closed = useRef(false)

  const flush = async () => {
    if (busy.current || closed.current || !pending.current.length) return

    busy.current = true
    const events = pending.current
    pending.current = []

    const sent = await deliver(events).catch(reportError)
    if (sent && !sent.open) closed.current = true

    busy.current = false
    void flush()
  }

  return (event: ScreenEvent, live: boolean) => {
    if (!live || closed.current) return
    const last = pending.current.at(-1)
    if (event.event === 'mouseMoved' && last?.event === 'mouseMoved') pending.current.pop()
    pending.current.push(event)
    void flush()
  }
}

export function LiveScreen({
  streamUrl,
  send: deliver,
  address: startAddress,
  label,
  starting,
  status,
  closeLabel,
  onClose,
  overlay,
  strip,
  focusOnStart = true,
  onStageResize,
  loading,
}: {
  streamUrl: string
  send: SendScreen
  address: string
  label: string
  starting: ReactNode
  status?: ReactNode
  closeLabel: string
  onClose: () => void
  overlay?: (size: FrameSize) => ReactNode
  strip?: ReactNode
  focusOnStart?: boolean
  onStageResize?: (size: FrameSize) => void
  loading?: string | null
}) {
  const [frame, setFrame] = useState<Frame>()
  const [phase, setPhase] = useState<Phase>('starting')
  const [focused, setFocused] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const keys = useRef<HTMLTextAreaElement>(null)
  const surface = useRef<HTMLImageElement>(null)
  const stage = useRef<HTMLDivElement>(null)
  const resized = useRef(onStageResize)
  resized.current = onStageResize
  const sendTo = useSender(deliver)
  const send = (event: ScreenEvent) => sendTo(event, phase === 'live')
  const size = frame ?? screenSize()

  useEffect(() => {
    const source = new EventSource(streamUrl)
    source.onmessage = (e) => {
      setFrame(JSON.parse(e.data as string) as Frame)
      setPhase('live')
    }
    source.addEventListener('end', (e) => {
      setFailure((JSON.parse((e as MessageEvent<string>).data) as { error: string | null }).error)
      source.close()
      setPhase('gone')
    })
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setPhase('gone')
    }
    return () => source.close()
  }, [streamUrl])

  useEffect(() => {
    if (phase === 'live' && focusOnStart) keys.current?.focus()
  }, [phase, focusOnStart])

  useEffect(() => {
    const el = stage.current
    if (!el || !resized.current) return

    let timer: ReturnType<typeof setTimeout> | undefined
    let last = ''
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.round(entry.contentRect.width)
      const height = Math.round(entry.contentRect.height)
      const key = `${width}x${height}`
      if (key === last || !width || !height) return

      clearTimeout(timer)
      timer = setTimeout(() => {
        last = key
        resized.current?.({ width, height })
      }, RESIZE_SETTLE_MS)
    })
    observer.observe(el)

    return () => {
      clearTimeout(timer)
      observer.disconnect()
    }
  }, [])

  useEffect(() => {
    const el = surface.current
    if (!el || !frame) return

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const at = point(e)
      if (at) send({ type: 'wheel', ...at, dx: e.deltaX, dy: e.deltaY })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })

  const point = (e: { clientX: number; clientY: number }) => {
    const rect = surface.current?.getBoundingClientRect()
    if (!rect || !frame) return undefined
    return {
      x: ((e.clientX - rect.left) * frame.width) / rect.width,
      y: ((e.clientY - rect.top) * frame.height) / rect.height,
    }
  }

  const mouse = (event: string) => (e: ReactMouseEvent) => {
    const at = point(e)
    if (!at) return

    if (event === 'mousePressed') {
      e.preventDefault()
      keys.current?.focus()
    }

    send({
      type: 'mouse',
      event,
      ...at,
      button: event === 'mouseMoved' ? 'none' : (BUTTON_NAMES[e.button] ?? 'left'),
      buttons: e.buttons,
      clickCount: event === 'mouseMoved' ? 0 : e.detail || 1,
      modifiers: modifiers(e),
    })
  }

  const key = (event: 'down' | 'up') => (e: ReactKeyboardEvent) => {
    e.stopPropagation()
    const command = e.ctrlKey || e.metaKey
    if (command && e.key.toLowerCase() === 'v') return

    e.preventDefault()
    if (e.nativeEvent.isComposing) return

    const typed = e.key.length === 1 && !command && !e.altKey
    const text = typed ? e.key : e.key === 'Enter' ? '\r' : undefined
    send({
      type: 'key',
      event: event === 'up' ? 'keyUp' : text ? 'keyDown' : 'rawKeyDown',
      key: e.key,
      code: e.code,
      keyCode: e.keyCode,
      modifiers: modifiers(e),
      text: event === 'down' ? text : undefined,
      commands:
        event === 'down' && command && e.key.toLowerCase() === 'a' ? ['selectAll'] : undefined,
    })
  }

  const painted = frame && frame.url !== BLANK_PAGE ? frame.url : startAddress
  const address = loading ?? painted
  const shown = splitAddress(address)
  const { href } = shown
  const [copied, copy] = useCopy()

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="border-line relative flex shrink-0 items-center gap-2 border-b px-3"
        style={{ height: SCREEN_BAR_PX }}
      >
        {loading ? (
          <div className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden">
            <div className="bg-brand animate-load-bar h-full w-2/5 rounded-full" />
          </div>
        ) : null}
        <button
          type="button"
          aria-label="Back"
          title="Back"
          disabled={phase !== 'live'}
          onClick={() => send({ type: 'back' })}
          className="text-muted hover:bg-raised hover:text-fg disabled:text-faint flex size-8 shrink-0 items-center justify-center rounded-full transition-colors"
        >
          <ArrowLeftIcon className="size-4" />
        </button>
        <div className="bg-raised text-text flex h-8 min-w-0 flex-1 items-center gap-2 rounded-full pr-1 pl-3 text-[12.5px]">
          {shown.secure ? (
            <LockClosedIcon
              className={cn('size-3.5 shrink-0', loading ? 'text-faint' : 'text-ok')}
            />
          ) : (
            <GlobeAltIcon className="text-muted size-3.5 shrink-0" />
          )}
          <span
            className={cn(
              'text-fg shrink-0 font-semibold whitespace-nowrap',
              shown.rest && 'border-line-strong border-r pr-2',
            )}
          >
            {shown.host}
          </span>
          <span
            className="text-faint min-w-0 flex-1 truncate font-mono text-[11.5px]"
            title={address}
          >
            {loading ? <Shimmer>{shown.rest}</Shimmer> : shown.rest}
          </span>
          {href ? (
            <>
              <button
                type="button"
                aria-label="Copy the address"
                title={copied ? 'Copied' : 'Copy the address'}
                onClick={() => copy(href)}
                className={BAR_ACTION}
              >
                {copied ? (
                  <CheckIcon className="animate-check text-ok size-3.5" />
                ) : (
                  <CopyIcon className="size-3.5" />
                )}
              </button>
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                aria-label="Open in your browser"
                title="Open in your browser"
                className={BAR_ACTION}
              >
                <OpenIcon className="size-3.5" />
              </a>
            </>
          ) : null}
        </div>
        {status}
        <button
          type="button"
          aria-label={closeLabel}
          title={closeLabel}
          onClick={onClose}
          className="text-faint hover:text-fg hover:bg-raised flex size-8 shrink-0 items-center justify-center rounded-full transition-colors"
        >
          <XMarkIcon className="size-4" />
        </button>
      </div>
      {strip}

      <div
        ref={stage}
        className="bg-raised flex min-h-0 flex-1 items-center justify-center overflow-hidden"
        style={{ containerType: 'size' }}
      >
        <div
          className="relative overflow-hidden bg-white"
          style={{
            aspectRatio: `${size.width} / ${size.height}`,
            width: `min(100cqw, ${size.width}px, calc(100cqh * ${size.width} / ${size.height}))`,
          }}
        >
          {frame ? (
            <img
              ref={surface}
              src={`data:image/jpeg;base64,${frame.data}`}
              alt={label}
              draggable={false}
              onMouseDown={mouse('mousePressed')}
              onMouseUp={mouse('mouseReleased')}
              onMouseMove={mouse('mouseMoved')}
              onContextMenu={(e) => e.preventDefault()}
              className={cn(
                'block size-full cursor-default select-none',
                phase === 'gone' && 'opacity-60',
              )}
            />
          ) : null}
          {phase !== 'live' ? (
            <div className="text-muted absolute inset-0 flex flex-col items-center justify-center gap-3 text-[13px]">
              {phase === 'starting' ? (
                <Shimmer className="text-[14px] font-medium">{starting}</Shimmer>
              ) : frame ? null : (
                (failure ?? 'The page is not shown here.')
              )}
            </div>
          ) : null}
          {phase === 'live' && focusOnStart && !focused ? (
            <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-[#263238]/75 px-3 py-1 text-[11.5px] text-white">
              Click the page to type
            </div>
          ) : null}
          {overlay?.(size)}
          <textarea
            ref={keys}
            aria-label={`Type into ${label}`}
            onKeyDown={key('down')}
            onKeyUp={key('up')}
            onPaste={(e) => {
              e.preventDefault()
              const text = e.clipboardData.getData('text')
              if (text) send({ type: 'text', text })
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            className="pointer-events-none absolute top-0 left-0 size-px resize-none opacity-0"
          />
        </div>
      </div>
    </div>
  )
}
