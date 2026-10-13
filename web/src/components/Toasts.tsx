import { Warning as ExclamationTriangleIcon, X as XMarkIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'

const TOAST_MS = 8000

type Toast = {
  id: number
  message: string
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
      setToasts((all) => [...all.filter((t) => t.message !== toast.message), toast])
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
      {toasts.map((t) =>
        t.action ? (
          <div
            key={t.id}
            role="status"
            className="animate-toast border-line-strong/70 relative overflow-hidden rounded-2xl border bg-white shadow-[0_8px_28px_rgba(38,50,56,0.16)]"
          >
            <div className="flex items-center gap-3 py-2 pr-2 pl-4">
              <span className="text-fg min-w-0 flex-1 text-[13px]">{t.message}</span>
              <button
                type="button"
                onClick={() => {
                  t.action?.run()
                  setToasts((all) => all.filter((x) => x.id !== t.id))
                }}
                className="bg-brand-soft text-brand-strong hover:bg-brand-chip inline-flex h-8 shrink-0 items-center gap-2 rounded-full pr-1.5 pl-3.5 text-[12.5px] font-semibold transition-colors"
              >
                {t.action.label}
                <kbd className="text-brand-strong/70 rounded-full bg-white px-2 py-0.5 font-sans text-[10.5px] font-medium">
                  Ctrl Z
                </kbd>
              </button>
            </div>
            <div
              className="bg-brand animate-toast-timer absolute bottom-0 left-0 h-[3px] w-full origin-left"
              style={{ animationDuration: `${t.ms ?? TOAST_MS}ms` }}
            />
          </div>
        ) : (
          <div
            key={t.id}
            role="alert"
            className="animate-toast border-danger/25 flex items-start gap-2.5 rounded-2xl border bg-white px-4 py-3 text-[12.5px] shadow-[0_8px_28px_rgba(38,50,56,0.16)]"
          >
            <ExclamationTriangleIcon className="text-danger mt-0.5 size-4 shrink-0" />
            <span className="text-text min-w-0 flex-1 break-words">{t.message}</span>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}
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
