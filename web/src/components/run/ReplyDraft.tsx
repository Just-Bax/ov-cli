import {
  ArrowsClockwise as ArrowPathIcon,
  EnvelopeSimple as EnvelopeIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button, CopyButton, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { useLayer } from '@/lib/layers'

export function ReplyDraft({
  runId,
  messageId,
  onClose,
}: {
  runId: string
  messageId: string
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(true)
  const edited = useRef(false)
  const latest = useRef(0)

  const draft = () => {
    const ticket = ++latest.current
    setLoading(true)
    setError(undefined)
    api
      .draftReply(runId, messageId)
      .then((r) => {
        if (ticket !== latest.current) return
        edited.current = false
        setText(r.text)
      })
      .catch((e: Error) => ticket === latest.current && setError(e.message))
      .finally(() => ticket === latest.current && setLoading(false))
  }

  useEffect(draft, [runId, messageId])

  useLayer(() => !edited.current && onClose())

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-label="Case reply"
        className="animate-pop flex max-h-[80vh] w-full max-w-[640px] flex-col rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.25)]"
      >
        <div className="flex items-center gap-3 px-5 pt-5">
          <span className="bg-brand-soft text-brand-strong flex size-9 items-center justify-center rounded-full">
            <EnvelopeIcon className="size-4.5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-fg text-[15px] font-semibold">Case reply</div>
            <div className="text-muted text-[12px]">
              Written from this answer in your reply style. Edit it before posting.
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="text-faint hover:text-fg hover:bg-raised flex size-8 items-center justify-center rounded-full"
          >
            <XMarkIcon className="size-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pt-4">
          {loading ? (
            <div className="space-y-2.5 py-1">
              <Skeleton className="w-1/3" />
              <Skeleton className="w-full" />
              <Skeleton className="w-11/12" />
              <Skeleton className="w-4/5" />
            </div>
          ) : error ? (
            <div className="text-danger text-[12.5px]">{error}</div>
          ) : (
            <textarea
              value={text}
              onChange={(e) => {
                edited.current = true
                setText(e.target.value)
              }}
              aria-label="Reply text"
              className="border-line-strong focus:border-brand text-fg block field-sizing-content min-h-[200px] w-full resize-none rounded-2xl border px-4 py-3 text-[13.5px] leading-relaxed outline-none"
            />
          )}
        </div>
        <div className="flex justify-end gap-2 px-5 py-4">
          <Button variant="ghost" disabled={loading} onClick={draft}>
            <ArrowPathIcon className="size-4" /> Write again
          </Button>
          {text && !loading ? (
            <CopyButton text={text} label="Copy reply" variant="primary" />
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
