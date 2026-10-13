import { BellAlertIcon, ExclamationTriangleIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'

const TOAST_MS = 8000

type Toast = {
  id: number
  message: string
  title?: string
  onOpen?: () => void
  action?: { label: string; run: () => void }
  ms?: number
}

let listeners: ((toast: Toast) => void)[] = []
let nextId = 0

export function reportError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error)
  const toast = { id: ++nextId, message }
  for (const listen of listeners) listen(toast)
}

export function notifyInApp(title: string, message: string, onOpen: () => void): void {
  const toast = { id: ++nextId, message, title, onOpen }
  for (const listen of listeners) listen(toast)
}

export function notifyAction(message: string, label: string, run: () => void, ms: number): number {
  const toast = { id: ++nextId, message, action: { label, run }, ms }
  for (const listen of listeners) listen(toast)
  return toast.id
}

let dismissers: ((id: number) => void)[] = []

export function dismissToast(id: number): void {
  for (const dismiss of dismissers) dismiss(id)
}

export function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    const listen = (toast: Toast) => {
      setToasts((all) => [
        ...all.filter((t) => t.message !== toast.message || t.title !== toast.title),
        toast,
      ])
      setTimeout(
        () => setToasts((all) => all.filter((t) => t.id !== toast.id)),
        toast.ms ?? TOAST_MS,
      )
    }
    const dismiss = (id: number) => setToasts((all) => all.filter((t) => t.id !== id))

    listeners.push(listen)
    dismissers.push(dismiss)
    return () => {
      listeners = listeners.filter((l) => l !== listen)
      dismissers = dismissers.filter((d) => d !== dismiss)
    }
  }, [])

  return (
    <div className="fixed right-4 bottom-4 z-[200] flex w-[360px] flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={cn(
            'animate-toast flex items-start gap-2.5 rounded-2xl border bg-white px-4 py-3 text-[12.5px] shadow-[0_8px_28px_rgba(38,50,56,0.16)]',
            t.action
              ? 'border-line-strong items-center'
              : t.onOpen
                ? 'border-brand/25'
                : 'border-danger/25',
          )}
        >
          {t.action ? (
            <>
              <span className="text-fg min-w-0 flex-1">{t.message}</span>
              <button
                type="button"
                onClick={() => {
                  t.action?.run()
                  setToasts((all) => all.filter((x) => x.id !== t.id))
                }}
                className="text-brand-strong hover:bg-brand-soft h-7 shrink-0 rounded-full px-3 font-semibold"
              >
                {t.action.label}
                <span className="text-faint ml-1.5 font-normal">Ctrl+Z</span>
              </button>
            </>
          ) : t.onOpen ? (
            <BellAlertIcon className="text-brand mt-0.5 size-4 shrink-0" />
          ) : (
            <ExclamationTriangleIcon className="text-danger mt-0.5 size-4 shrink-0" />
          )}
          {t.action ? null : t.onOpen ? (
            <button
              type="button"
              onClick={() => {
                t.onOpen?.()
                setToasts((all) => all.filter((x) => x.id !== t.id))
              }}
              className="min-w-0 flex-1 text-left break-words"
            >
              <span className="text-fg block font-semibold">{t.title}</span>
              <span className="text-text">{t.message}</span>
            </button>
          ) : (
            <span className="text-text min-w-0 flex-1 break-words">{t.message}</span>
          )}
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}
            className="text-faint hover:text-fg -mr-1 flex size-5 shrink-0 items-center justify-center rounded-full"
          >
            <XMarkIcon className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}
