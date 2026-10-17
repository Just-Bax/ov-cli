import {
  ArrowBendUpRight as SteerIcon,
  CaretDown as CaretDownIcon,
  FileText as DocumentTextIcon,
  ListNumbers as QueueIcon,
  PencilSimple as PencilIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useState } from 'react'
import type { ChatMessage } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Shimmer } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

const ROW_ACTION =
  'text-muted hover:bg-black/[0.06] hover:text-fg flex h-7 shrink-0 items-center justify-center gap-1 rounded-full transition-colors'

export function QueuedPanel({ runId, queued }: { runId: string; queued: ChatMessage[] }) {
  const [collapsed, setCollapsed] = useState(false)
  if (!queued.length) return null

  return (
    <div className="border-line-strong bg-canvas relative mx-4 -mb-6 rounded-t-[22px] border border-b-0 px-3 pt-2 pb-7">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="text-muted hover:text-fg flex h-7 w-full items-center gap-2 px-1 text-[12.5px]"
      >
        <QueueIcon className="size-3.5" />
        <span className="font-medium">Queued</span>
        <span className="flex-1" />
        <span className="text-fg font-semibold tabular-nums">{queued.length}</span>
        <CaretDownIcon className={cn('size-3.5 transition-transform', collapsed && 'rotate-180')} />
      </button>
      {collapsed ? null : (
        <div className="max-h-48 scrollbar-thin overflow-y-auto">
          {queued.map((m) => (
            <QueuedRow key={m.id} runId={runId} message={m} />
          ))}
        </div>
      )}
    </div>
  )
}

function QueuedRow({ runId, message }: { runId: string; message: ChatMessage }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(message.text)
  const files = message.files ?? []

  const save = () => {
    setEditing(false)
    if (text.trim() === message.text.trim()) return
    void api.editQueued(runId, message.id, text.trim()).catch((e: unknown) => {
      setText(message.text)
      reportError(e)
    })
  }

  return (
    <div className="group flex min-h-9 items-center gap-2 rounded-xl px-1 text-[13px]">
      {files.map((f) =>
        f.kind === 'image' ? (
          <img
            key={f.name}
            src={api.fileUrl(runId, f.name)}
            alt={f.name}
            title={f.name}
            className="border-line size-6 shrink-0 rounded-md border bg-white object-cover"
          />
        ) : (
          <span key={f.name} title={f.name} className="text-muted shrink-0">
            <DocumentTextIcon className="size-4" />
          </span>
        ),
      )}
      {editing ? (
        <textarea
          autoFocus
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              save()
            }
            if (e.key === 'Escape') {
              setText(message.text)
              setEditing(false)
            }
          }}
          className="border-line-strong focus:border-brand text-fg field-sizing-content max-h-32 min-w-0 flex-1 resize-none rounded-lg border bg-white px-2 py-1 outline-none"
        />
      ) : (
        <span className="text-fg min-w-0 flex-1 truncate" title={message.text}>
          {message.text}
        </span>
      )}
      {editing ? null : (
        <button
          type="button"
          title="Edit"
          aria-label="Edit queued message"
          onClick={() => setEditing(true)}
          className={cn(ROW_ACTION, 'w-7')}
        >
          <PencilIcon className="size-3.5" />
        </button>
      )}
      {message.steer ? (
        <Shimmer tone="brand" className="shrink-0 px-2 text-[12.5px] font-medium">
          Steering
        </Shimmer>
      ) : (
        <button
          type="button"
          title="Send now, picked up at the next step"
          onClick={() => void api.steerQueued(runId, message.id).catch(reportError)}
          className={cn(ROW_ACTION, 'px-2 text-[12.5px] font-medium')}
        >
          <SteerIcon className="size-3.5" />
          Steer
        </button>
      )}
      <button
        type="button"
        title="Remove from queue"
        aria-label="Remove from queue"
        onClick={() => void api.removeQueued(runId, message.id).catch(reportError)}
        className={cn(ROW_ACTION, 'w-7')}
      >
        <XMarkIcon className="size-3.5" />
      </button>
    </div>
  )
}
