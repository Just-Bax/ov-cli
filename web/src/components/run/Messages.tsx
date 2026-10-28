import {
  ArrowUUpLeft as ArrowUturnLeftIcon,
  Check as CheckIcon,
  FileText as DocumentTextIcon,
  Copy as Square2StackIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import type { ChatMessage, MessageFile } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Markdown, useCopy } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { timeWithDay } from '@/lib/time'
import { FilePreview } from './FilePreview'

const LONG_MESSAGE_CHARS = 1200
const LONG_MESSAGE_LINES = 14

function formatTime(ts: number): string {
  return timeWithDay(ts, { month: 'short', day: 'numeric' })
}

function ActionButton({
  label,
  onClick,
  busy = false,
  children,
}: {
  label: string
  onClick: () => void
  busy?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={busy}
      className={cn(
        'text-faint hover:bg-raised hover:text-fg flex size-7 items-center justify-center rounded-full transition-colors',
        busy && 'busy-sweep',
      )}
    >
      {children}
    </button>
  )
}

function CopyAction({ text }: { text: string }) {
  const [copied, copy] = useCopy()

  return (
    <ActionButton label={copied ? 'Copied' : 'Copy'} onClick={() => copy(text)}>
      {copied ? (
        <CheckIcon className="text-ok size-3.5" />
      ) : (
        <Square2StackIcon className="size-3.5" />
      )}
    </ActionButton>
  )
}

function RetryButton({ label, runId, itemId }: { label: string; runId: string; itemId: string }) {
  const [retrying, setRetrying] = useState(false)

  return (
    <ActionButton
      label={label}
      busy={retrying}
      onClick={() => {
        setRetrying(true)
        api
          .retry(runId, itemId)
          .catch(reportError)
          .finally(() => setRetrying(false))
      }}
    >
      <ArrowUturnLeftIcon className="size-3.5" />
    </ActionButton>
  )
}

function FileChips({ runId, files }: { runId: string; files: MessageFile[] }) {
  const [open, setOpen] = useState<number>()
  if (!files.length) return null

  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {files.map((f, i) =>
        f.kind === 'image' ? (
          <button
            key={f.name}
            type="button"
            title={f.name}
            aria-label={`Preview ${f.name}`}
            onClick={() => setOpen(i)}
            className="cursor-zoom-in"
          >
            <img
              src={api.imageUrl(runId, f)}
              alt={f.name}
              className="border-line bg-raised h-28 max-w-[260px] rounded-2xl border object-contain transition-opacity hover:opacity-90"
            />
          </button>
        ) : (
          <button
            key={f.name}
            type="button"
            title={f.name}
            aria-label={`Preview ${f.name}`}
            onClick={() => setOpen(i)}
            className="border-line text-text hover:bg-raised inline-flex h-9 items-center gap-2 rounded-full border bg-white px-3 text-[12.5px] transition-colors"
          >
            <DocumentTextIcon className="text-muted size-4" />
            <span className="max-w-[200px] truncate">{f.name}</span>
          </button>
        ),
      )}
      {open !== undefined ? (
        <FilePreview runId={runId} files={files} start={open} onClose={() => setOpen(undefined)} />
      ) : null}
    </div>
  )
}

function UserText({ text }: { text: string }) {
  const long = text.length > LONG_MESSAGE_CHARS || text.split('\n').length > LONG_MESSAGE_LINES
  const [open, setOpen] = useState(false)

  return (
    <div className="bg-canvas text-fg max-w-[80%] min-w-0 rounded-3xl px-4 py-2.5 text-[14px]">
      <div className={cn('user-md relative', long && !open && 'max-h-[260px] overflow-hidden')}>
        <Markdown text={text} />
        {long && !open ? (
          <div className="from-canvas pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t to-transparent" />
        ) : null}
      </div>
      {long ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-brand-strong mt-1 text-[12px] font-medium hover:underline"
        >
          {open ? 'Show less' : 'Show more'}
        </button>
      ) : null}
    </div>
  )
}

export function UserMessage({
  runId,
  message,
  canRetry,
}: {
  runId: string
  message: ChatMessage
  canRetry: boolean
}) {
  return (
    <div className="group flex flex-col items-end gap-1.5">
      <FileChips runId={runId} files={message.files ?? []} />
      {message.text ? <UserText text={message.text} /> : null}
      <div className="flex h-7 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <span className="text-faint mr-1 text-[11.5px]">{formatTime(message.ts)}</span>
        {canRetry ? (
          <RetryButton label="Retry from here" runId={runId} itemId={message.id} />
        ) : null}
        <CopyAction text={message.text} />
      </div>
    </div>
  )
}

export function AssistantActions({
  runId,
  turnId,
  text,
  ts,
  canRetry,
}: {
  runId: string
  turnId: string
  text: string
  ts?: number
  canRetry: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-0.5">
      <CopyAction text={text} />
      {canRetry ? <RetryButton label="Retry" runId={runId} itemId={turnId} /> : null}
      {ts ? <span className="text-faint ml-1.5 text-[11.5px]">{formatTime(ts)}</span> : null}
    </div>
  )
}
