import {
  ArrowUturnLeftIcon,
  CheckIcon,
  DocumentTextIcon,
  HandThumbDownIcon,
  HandThumbUpIcon,
  Square2StackIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { type ReactNode, useState } from 'react'
import type { ChatMessage, MessageFile, Rating } from '@shared/types.ts'
import { Spinner, Markdown } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

const COPIED_FEEDBACK_MS = 1200

function formatTime(ts: number): string {
  const d = new Date(ts)
  const today = new Date().toDateString() === d.toDateString()
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return today ? time : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${time}`
}

function ActionButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string
  onClick: () => void
  active?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={cn(
        'flex size-7 items-center justify-center rounded-full transition-colors',
        active ? 'text-brand-strong bg-brand-soft' : 'text-faint hover:bg-raised hover:text-fg',
      )}
    >
      {children}
    </button>
  )
}

function CopyAction({ text }: { text: string }) {
  const [done, setDone] = useState(false)

  return (
    <ActionButton
      label={done ? 'Copied' : 'Copy'}
      onClick={() => {
        void navigator.clipboard.writeText(text)
        setDone(true)
        setTimeout(() => setDone(false), COPIED_FEEDBACK_MS)
      }}
    >
      {done ? (
        <CheckIcon className="text-ok size-3.5" />
      ) : (
        <Square2StackIcon className="size-3.5" />
      )}
    </ActionButton>
  )
}

function FileChips({ runId, files }: { runId: string; files: MessageFile[] }) {
  if (!files.length) return null

  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {files.map((f) =>
        f.kind === 'image' ? (
          <a
            key={f.name}
            href={api.fileUrl(runId, f.name)}
            target="_blank"
            rel="noreferrer"
            title={f.name}
          >
            <img
              src={api.fileUrl(runId, f.name)}
              alt={f.name}
              className="border-line bg-raised h-28 max-w-[260px] rounded-2xl border object-contain transition-opacity hover:opacity-90"
            />
          </a>
        ) : (
          <a
            key={f.name}
            href={api.fileUrl(runId, f.name)}
            target="_blank"
            rel="noreferrer"
            className="border-line text-text hover:bg-raised inline-flex h-9 items-center gap-2 rounded-full border bg-white px-3 text-[12.5px]"
          >
            <DocumentTextIcon className="text-muted size-4" />
            <span className="max-w-[200px] truncate">{f.name}</span>
          </a>
        ),
      )}
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

const LONG_MESSAGE_CHARS = 1200
const LONG_MESSAGE_LINES = 14

export function UserMessage({
  runId,
  message,
  canRetry,
}: {
  runId: string
  message: ChatMessage
  canRetry: boolean
}) {
  const [retrying, setRetrying] = useState(false)

  return (
    <div className="group flex flex-col items-end gap-1.5">
      <FileChips runId={runId} files={message.files ?? []} />
      {message.text ? <UserText text={message.text} /> : null}
      <div className="flex h-7 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <span className="text-faint mr-1 text-[11.5px]">{formatTime(message.ts)}</span>
        {canRetry ? (
          <ActionButton
            label="Retry from here"
            onClick={() => {
              setRetrying(true)
              void api.retry(runId, message.id).finally(() => setRetrying(false))
            }}
          >
            {retrying ? (
              <Spinner className="size-3.5" />
            ) : (
              <ArrowUturnLeftIcon className="size-3.5" />
            )}
          </ActionButton>
        ) : null}
        <CopyAction text={message.text} />
      </div>
    </div>
  )
}

export function QueuedMessage({ runId, message }: { runId: string; message: ChatMessage }) {
  return (
    <div className="flex flex-col items-end gap-1.5 opacity-70">
      <FileChips runId={runId} files={message.files ?? []} />
      <div className="border-line-strong text-fg max-w-[80%] rounded-3xl border border-dashed px-4 py-2.5 text-[14px] whitespace-pre-wrap">
        {message.text}
      </div>
      <div className="text-faint flex h-7 items-center gap-1 text-[11.5px]">
        <Spinner className="text-brand size-3" /> Queued, sent when the agent can take it
        <button
          type="button"
          title="Remove from queue"
          onClick={() => void api.removeQueued(runId, message.id)}
          className="hover:bg-raised hover:text-fg flex size-6 items-center justify-center rounded-full"
        >
          <XMarkIcon className="size-3.5" />
        </button>
      </div>
    </div>
  )
}

export function AssistantActions({
  runId,
  turnId,
  text,
  ts,
  rating,
  canRetry,
  onRated,
}: {
  runId: string
  turnId: string
  text: string
  ts?: number
  rating?: { rating: Rating; note?: string }
  canRetry: boolean
  onRated?: (rating: Rating | null, note?: string) => void
}) {
  const [current, setCurrent] = useState<Rating | undefined>(rating?.rating)
  const [note, setNote] = useState(rating?.note ?? '')
  const [sentNote, setSentNote] = useState(rating?.note ?? '')
  const [retrying, setRetrying] = useState(false)

  const rate = (r: Rating) => {
    const next = current === r ? null : r
    setCurrent(next ?? undefined)
    onRated?.(next, note)
    void api.rate(runId, turnId, next, note)
  }

  return (
    <div className="flex flex-wrap items-center gap-0.5">
      <CopyAction text={text} />
      <ActionButton label="Good response" active={current === 'good'} onClick={() => rate('good')}>
        <HandThumbUpIcon className="size-3.5" />
      </ActionButton>
      <ActionButton label="Bad response" active={current === 'wrong'} onClick={() => rate('wrong')}>
        <HandThumbDownIcon className="size-3.5" />
      </ActionButton>
      {canRetry ? (
        <ActionButton
          label="Retry"
          onClick={() => {
            setRetrying(true)
            void api.retry(runId, turnId).finally(() => setRetrying(false))
          }}
        >
          {retrying ? (
            <Spinner className="size-3.5" />
          ) : (
            <ArrowUturnLeftIcon className="size-3.5" />
          )}
        </ActionButton>
      ) : null}
      {ts ? <span className="text-faint ml-1.5 text-[11.5px]">{formatTime(ts)}</span> : null}
      {current === 'wrong' ? (
        <form
          className="border-line-strong focus-within:border-brand ml-2 flex h-7 w-[300px] max-w-full items-center rounded-full border bg-white pr-1 pl-3"
          onSubmit={(e) => {
            e.preventDefault()
            const value = note.trim()
            if (!value || value === sentNote) return
            onRated?.('wrong', value)
            void api.rate(runId, turnId, 'wrong', value).then(() => setSentNote(value))
          }}
        >
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What was wrong? (optional)"
            className="placeholder:text-faint text-fg min-w-0 flex-1 bg-transparent text-[12px] outline-none"
          />
          {note.trim() && note.trim() === sentNote ? (
            <CheckIcon className="text-ok mr-1.5 size-3.5" />
          ) : (
            <button
              type="submit"
              disabled={!note.trim()}
              className="text-brand disabled:text-faint px-1.5 text-[11.5px] font-medium"
            >
              Send
            </button>
          )}
        </form>
      ) : null}
    </div>
  )
}
