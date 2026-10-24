import {
  CircleNotch as SpinnerIcon,
  Warning as ExclamationTriangleIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type AnimationEvent, useEffect, useState } from 'react'
import { cn } from '@/lib/cn'

const TOAST_MS = 8000
const RING_RADIUS = 7.5

type Toast = {
  id: number
  message: string
  action?: { label: string; run: () => void }
  ms?: number
  progress?: boolean
  leaving?: boolean
}

let listeners: ((toast: Toast) => void)[] = []
let nextId = 0
let dismissers: ((id: number) => void)[] = []

function emit(toast: Toast): number {
  for (const listen of listeners) listen(toast)
  return toast.id
}

export function reportError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error)
  emit({ id: ++nextId, message })
}

export function notifyAction(message: string, label: string, run: () => void, ms: number): number {
  return emit({ id: ++nextId, message, action: { label, run }, ms })
}

export function notifyProgress(message: string): number {
  return emit({ id: ++nextId, message, progress: true })
}

export async function withProgress<T>(message: string, work: () => Promise<T>): Promise<T> {
  const id = notifyProgress(message)
  try {
    return await work()
  } finally {
    dismissToast(id)
  }
}

export function dismissToast(id: number): void {
  for (const dismiss of dismissers) dismiss(id)
}

export function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const remove = (id: number) =>
    setToasts((all) => all.map((t) => (t.id === id ? { ...t, leaving: true } : t)))
  const drop = (id: number) => setToasts((all) => all.filter((t) => t.id !== id))
  const motion = (t: Toast) =>
    t.leaving ? 'animate-toast-out pointer-events-none' : 'animate-toast'
  const dropAfterExit = (t: Toast) => (e: AnimationEvent) =>
    t.leaving && e.target === e.currentTarget && drop(t.id)

  useEffect(() => {
    const timers = new Set<ReturnType<typeof setTimeout>>()
    const listen = (toast: Toast) => {
      setToasts((all) => [...all.filter((t) => t.message !== toast.message), toast])
      if (toast.progress) return

      const timer = setTimeout(() => {
        timers.delete(timer)
        remove(toast.id)
      }, toast.ms ?? TOAST_MS)
      timers.add(timer)
    }

    listeners.push(listen)
    dismissers.push(remove)
    return () => {
      for (const timer of timers) clearTimeout(timer)
      listeners = listeners.filter((l) => l !== listen)
      dismissers = dismissers.filter((d) => d !== remove)
    }
  }, [])

  return (
    <div className="fixed right-4 bottom-4 z-[200] flex w-[360px] flex-col gap-2">
      {toasts.map((t) =>
        t.progress ? (
          <div
            key={t.id}
            role="status"
            onAnimationEnd={dropAfterExit(t)}
            className={cn(
              motion(t),
              'border-line-strong/70 flex items-center gap-3 rounded-full border bg-white px-4 py-2.5 shadow-[0_8px_28px_rgba(38,50,56,0.16)]',
            )}
          >
            <SpinnerIcon className="text-brand size-4 shrink-0 animate-spin" />
            <span className="text-fg min-w-0 flex-1 truncate text-[13px]">{t.message}</span>
          </div>
        ) : t.action ? (
          <div
            key={t.id}
            role="status"
            onAnimationEnd={dropAfterExit(t)}
            className={cn(
              motion(t),
              'border-line-strong/70 flex items-center gap-3 rounded-full border bg-white py-1.5 pr-1.5 pl-4 shadow-[0_8px_28px_rgba(38,50,56,0.16)]',
            )}
          >
            <svg viewBox="0 0 20 20" className="text-brand size-4 shrink-0 -rotate-90" aria-hidden>
              <circle
                cx="10"
                cy="10"
                r={RING_RADIUS}
                className="stroke-line"
                strokeWidth="2.5"
                fill="none"
              />
              <circle
                cx="10"
                cy="10"
                r={RING_RADIUS}
                stroke="currentColor"
                strokeWidth="2.5"
                fill="none"
                strokeLinecap="round"
                pathLength="1"
                strokeDasharray="1"
                className="animate-toast-ring"
                style={{ animationDuration: `${t.ms ?? TOAST_MS}ms` }}
              />
            </svg>
            <span className="text-fg min-w-0 flex-1 truncate text-[13px]">{t.message}</span>
            <button
              type="button"
              onClick={() => {
                t.action?.run()
                remove(t.id)
              }}
              className="bg-brand-soft text-brand-strong hover:bg-brand-chip inline-flex h-8 shrink-0 items-center gap-2 rounded-full pr-1.5 pl-3.5 text-[12.5px] font-semibold transition-colors"
            >
              {t.action.label}
              <kbd className="text-brand-strong/70 rounded-full bg-white px-2 py-0.5 font-sans text-[10.5px] font-medium">
                Ctrl Z
              </kbd>
            </button>
          </div>
        ) : (
          <div
            key={t.id}
            role="alert"
            onAnimationEnd={dropAfterExit(t)}
            className={cn(
              motion(t),
              'border-danger/25 flex items-start gap-2.5 rounded-2xl border bg-white px-4 py-3 text-[12.5px] shadow-[0_8px_28px_rgba(38,50,56,0.16)]',
            )}
          >
            <ExclamationTriangleIcon className="text-danger mt-0.5 size-4 shrink-0" />
            <span className="text-text min-w-0 flex-1 break-words">{t.message}</span>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => remove(t.id)}
              className="text-faint hover:text-fg -mr-1 flex size-5 shrink-0 items-center justify-center rounded-full"
            >
              <XMarkIcon className="size-3.5" />
            </button>
          </div>
        ),
      )}
    </div>
  )
}
