import {
  ArrowLeft as ArrowLeftIcon,
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
import { Spinner } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

export const SCREEN_BAR_PX = 52
const SCREEN_MARGIN_PX = 48
const MAX_SCREEN_WIDTH = 1280
const MAX_SCREEN_HEIGHT = 900

const MODIFIER = { alt: 1, ctrl: 2, meta: 4, shift: 8 }
const BUTTON_NAMES = ['left', 'middle', 'right'] as const

type Frame = { data: string; url: string; width: number; height: number }
type ScreenEvent = Record<string, unknown> & { type: string }
type Phase = 'starting' | 'live' | 'gone'

function splitAddress(address: string): { host: string; path: string; secure: boolean } {
  const full = /^[a-z][a-z0-9+.-]*:/i.test(address) ? address : `https://${address}`
  if (!URL.canParse(full)) return { host: address, path: '', secure: false }

  const url = new URL(full)
  return {
    host: url.host,
    path: url.pathname === '/' ? '' : url.pathname,
    secure: url.protocol === 'https:',
  }
}

export function screenSize(): { width: number; height: number } {
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

function useSender(url: string, tenant?: string) {
  const pending = useRef<ScreenEvent[]>([])
  const busy = useRef(false)

  const flush = async () => {
    if (busy.current || !pending.current.length) return

    busy.current = true
    const events = pending.current
    pending.current = []
    await api.signInInput(url, tenant, events).catch(reportError)
    busy.current = false
    void flush()
  }

  return (event: ScreenEvent, live: boolean) => {
    if (!live) return
    const last = pending.current.at(-1)
    if (event.event === 'mouseMoved' && last?.event === 'mouseMoved') pending.current.pop()
    pending.current.push(event)
    void flush()
  }
}

export function RemoteScreen({
  url,
  host,
  tenant,
  status,
  onCancel,
}: {
  url: string
  host: string
  tenant?: string
  status: ReactNode
  onCancel: () => void
}) {
  const [frame, setFrame] = useState<Frame>()
  const [phase, setPhase] = useState<Phase>('starting')
  const [focused, setFocused] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const keys = useRef<HTMLTextAreaElement>(null)
  const surface = useRef<HTMLImageElement>(null)
  const sendTo = useSender(url, tenant)
  const send = (event: ScreenEvent) => sendTo(event, phase === 'live')
  const size = frame ?? screenSize()

  useEffect(() => {
    const source = new EventSource(api.signInScreenUrl(url, tenant))
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
  }, [url, tenant])

  useEffect(() => {
    if (phase === 'live') keys.current?.focus()
  }, [phase])

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

  const address = frame?.url ?? url
  const shown = splitAddress(address)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="border-line flex shrink-0 items-center gap-2 border-b px-3"
        style={{ height: SCREEN_BAR_PX }}
      >
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
        <div className="bg-raised text-text flex h-8 min-w-0 flex-1 items-center gap-2 rounded-full px-3 text-[12.5px]">
          {shown.secure ? (
            <LockClosedIcon className="text-ok size-3.5 shrink-0" />
          ) : (
            <GlobeAltIcon className="text-muted size-3.5 shrink-0" />
          )}
          <span className="truncate" title={address}>
            <span className="text-fg">{shown.host}</span>
            <span className="text-faint">{shown.path}</span>
          </span>
        </div>
        {status}
        <button
          type="button"
          aria-label="Cancel sign-in"
          title="Cancel sign-in"
          onClick={onCancel}
          className="text-faint hover:text-fg hover:bg-raised flex size-8 shrink-0 items-center justify-center rounded-full transition-colors"
        >
          <XMarkIcon className="size-4" />
        </button>
      </div>

      <div
        className="bg-raised relative min-h-0 flex-1 overflow-hidden"
        style={{ aspectRatio: `${size.width} / ${size.height}`, maxWidth: size.width }}
      >
        {frame ? (
          <img
            ref={surface}
            src={`data:image/jpeg;base64,${frame.data}`}
            alt={`Sign-in page for ${host}`}
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
              <>
                <Spinner className="text-brand size-6" />
                Opening {host}
              </>
            ) : frame ? null : (
              (failure ?? 'The sign-in page is not shown here.')
            )}
          </div>
        ) : null}
        {phase === 'live' && !focused ? (
          <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-[#263238]/75 px-3 py-1 text-[11.5px] text-white">
            Click the page to type
          </div>
        ) : null}
        <textarea
          ref={keys}
          aria-label="Type into the sign-in page"
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
  )
}
