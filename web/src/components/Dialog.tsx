import {
  Warning as ExclamationTriangleIcon,
  Info as InformationCircleIcon,
  ShieldWarning as ShieldExclamationIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui'
import { useLayer } from '@/lib/layers'
import { cn } from '@/lib/cn'

type Tone = 'default' | 'danger' | 'warn'

interface DialogRequest {
  title: string
  body?: ReactNode
  confirmLabel?: string
  cancelLabel?: string | null
  tone?: Tone
  resolve: (ok: boolean) => void
}

let push: ((req: DialogRequest) => void) | undefined

export const dialog = {
  confirm(opts: Omit<DialogRequest, 'resolve'>): Promise<boolean> {
    if (!push) throw new Error('DialogHost is not mounted')
    const show = push
    return new Promise((resolve) => show({ ...opts, resolve }))
  },
  alert(title: string, body?: ReactNode, tone: Tone = 'danger'): Promise<void> {
    return dialog
      .confirm({ title, body, tone, confirmLabel: 'OK', cancelLabel: null })
      .then(() => undefined)
  },
}

const ICON: Record<Tone, ReactNode> = {
  default: <InformationCircleIcon className="text-brand size-5" />,
  warn: <ShieldExclamationIcon className="text-warn size-5" />,
  danger: <ExclamationTriangleIcon className="text-danger size-5" />,
}

const ICON_BG: Record<Tone, string> = {
  default: 'bg-brand-soft',
  warn: 'bg-warn-soft',
  danger: 'bg-danger-soft',
}

const CONFIRM_CLASS: Record<Tone, string> = {
  default: '',
  warn: 'bg-warn hover:bg-warn hover:brightness-95',
  danger: 'bg-danger hover:bg-danger hover:brightness-95',
}

export function DialogHost() {
  const [queue, setQueue] = useState<DialogRequest[]>([])
  const [shown, setShown] = useState(false)
  const confirmRef = useRef<HTMLButtonElement>(null)
  const closed = useRef<DialogRequest | undefined>(undefined)
  const current = queue[0]

  useEffect(() => {
    push = (req) => setQueue((q) => [...q, req])
    return () => {
      push = undefined
    }
  }, [])

  useEffect(() => {
    if (!current) return

    const frame = requestAnimationFrame(() => setShown(true))
    confirmRef.current?.focus()
    return () => cancelAnimationFrame(frame)
  }, [current])

  useLayer(() => current?.cancelLabel !== null && close(false), Boolean(current))

  const close = (ok: boolean) => {
    if (!current || closed.current === current) return
    closed.current = current
    current.resolve(ok)
    setShown(false)
    setQueue((q) => q.slice(1))
  }

  if (!current) return null

  const tone = current.tone ?? 'default'

  return createPortal(
    <div
      className={cn(
        'fixed inset-0 z-[100] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px] transition-opacity duration-200',
        shown ? 'opacity-100' : 'opacity-0',
      )}
      onMouseDown={(e) =>
        e.target === e.currentTarget && current.cancelLabel !== null && close(false)
      }
    >
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'ease-spring w-full max-w-[420px] rounded-2xl bg-white p-5 shadow-[0_20px_60px_rgba(38,50,56,0.25)] transition-[transform,opacity] duration-300',
          shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-6 scale-[0.97] opacity-0',
        )}
      >
        <div className="flex gap-3.5">
          <div
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-full',
              ICON_BG[tone],
            )}
          >
            {ICON[tone]}
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">{current.title}</div>
            {current.body ? (
              <div className="text-muted mt-1.5 text-[13px] leading-relaxed">{current.body}</div>
            ) : null}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          {current.cancelLabel !== null ? (
            <Button variant="ghost" size="lg" onClick={() => close(false)}>
              {current.cancelLabel ?? 'Cancel'}
            </Button>
          ) : null}
          <Button
            ref={confirmRef}
            variant="primary"
            size="lg"
            className={CONFIRM_CLASS[tone]}
            onClick={() => close(true)}
          >
            {current.confirmLabel ?? 'OK'}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
