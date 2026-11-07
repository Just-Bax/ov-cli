import {
  ArrowUp as ArrowUpIcon,
  CaretDown as CaretDownIcon,
  DotsSixVertical as GripIcon,
  FileText as DocumentTextIcon,
  PencilSimple as PencilIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import type { ChatMessage, RunStatus } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { useQueueActions } from '@/lib/queueActions'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { WORKING } from '@/lib/runs'
import { formatTime } from './Messages'
import { plural } from '@/lib/text'

const VISIBLE_QUEUED = 3
const ACTION =
  'text-muted hover:text-fg hover:bg-black/[0.06] flex h-6 shrink-0 items-center justify-center gap-1 rounded-full text-[12px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-40'
const DROP_LINE = 'bg-brand pointer-events-none absolute right-0 h-0.5 w-1/2 rounded-full'

type Drag = { id: string; insert: number | null }

export function QueuedMessages({
  runId,
  queued,
  held,
  status,
  editingId,
  canEdit,
  onEdit,
  onCancelEdit,
}: {
  runId: string
  queued: ChatMessage[]
  held: boolean
  status: RunStatus
  editingId?: string
  canEdit: boolean
  onEdit: (message: ChatMessage) => void
  onCancelEdit: () => void
}) {
  const [showAll, setShowAll] = useState(false)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [moving, setMoving] = useState(false)
  const armed = useRef<string | null>(null)
  const actions = useQueueActions(runId, queued, status)
  if (!queued.length) return null

  const collapsible = queued.length > VISIBLE_QUEUED
  const visible = collapsible && !showAll ? queued.slice(0, VISIBLE_QUEUED - 1) : queued

  const move = (id: string, before: string | null) => {
    setMoving(true)
    api
      .moveQueued(runId, id, before)
      .catch(reportError)
      .finally(() => setMoving(false))
  }

  const drop = ({ id, insert }: Drag) => {
    setDrag(null)
    armed.current = null
    const from = queued.findIndex((m) => m.id === id)
    if (insert === null || from < 0 || insert === from || insert === from + 1) return
    move(id, queued[insert]?.id ?? null)
  }

  return (
    <section
      aria-label={plural(queued.length, 'queued message')}
      className="flex flex-col items-end gap-3"
    >
      {held ? (
        <span className="bg-warn-soft text-warn rounded-full px-2 text-[11px] leading-[18px] font-semibold">
          Queue paused
        </span>
      ) : null}
      <ol className="flex w-full flex-col items-end gap-3">
        {visible.map((message, index) => {
          const editing = message.id === editingId
          const files = message.files ?? []

          return (
            <li
              key={message.id}
              aria-label={`Queued message ${index + 1} of ${queued.length}, not sent`}
              aria-current={editing || undefined}
              draggable={!moving}
              onDragStart={(e) => {
                if (armed.current !== message.id) {
                  e.preventDefault()
                  return
                }
                e.dataTransfer.effectAllowed = 'move'
                e.dataTransfer.setData('text/plain', message.id)
                setDrag({ id: message.id, insert: null })
              }}
              onDragEnd={() => {
                armed.current = null
                setDrag(null)
              }}
              onDragOver={(e) => {
                if (!drag) return
                e.preventDefault()
                const box = e.currentTarget.getBoundingClientRect()
                const insert = e.clientY < box.top + box.height / 2 ? index : index + 1
                if (drag.insert !== insert) setDrag({ ...drag, insert })
              }}
              onDrop={(e) => {
                if (!drag) return
                e.preventDefault()
                drop(drag)
              }}
              className={cn(
                'group relative flex w-full flex-col items-end gap-1',
                drag?.id === message.id && 'opacity-40',
              )}
            >
              {drag?.insert === index ? <span className={cn(DROP_LINE, '-top-2')} /> : null}
              {index === visible.length - 1 && drag?.insert === visible.length ? (
                <span className={cn(DROP_LINE, '-bottom-2')} />
              ) : null}
              <div
                className={cn(
                  'flex max-w-[80%] min-w-0 flex-col gap-2 rounded-3xl border border-dashed px-4 py-2.5 text-[14px]',
                  editing ? 'border-brand text-fg' : 'border-line-strong text-muted',
                )}
              >
                {files.length ? (
                  <span className="flex flex-wrap items-center gap-1">
                    {files.map((f, i) =>
                      f.kind === 'image' ? (
                        <img
                          key={i}
                          src={api.imageUrl(runId, f)}
                          alt={f.name}
                          title={f.name}
                          className="border-line size-8 rounded-md border object-cover"
                        />
                      ) : (
                        <span
                          key={i}
                          title={f.name}
                          className="border-line inline-flex h-8 max-w-[200px] items-center gap-1.5 rounded-md border px-2 text-[12px]"
                        >
                          <DocumentTextIcon className="size-3.5 shrink-0" />
                          <span className="truncate">{f.name}</span>
                        </span>
                      ),
                    )}
                  </span>
                ) : null}
                {message.text ? (
                  <p className="break-words whitespace-pre-wrap">{message.text}</p>
                ) : null}
              </div>
              <div className="flex h-7 items-center gap-0.5">
                <span className="flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                  {queued.length > 1 ? (
                    <button
                      type="button"
                      aria-label="Reorder queued message (drag, or press the arrow keys)"
                      disabled={moving}
                      onPointerDown={() => {
                        armed.current = message.id
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'ArrowUp' && index > 0) {
                          e.preventDefault()
                          move(message.id, queued[index - 1].id)
                        }
                        if (e.key === 'ArrowDown' && index < queued.length - 1) {
                          e.preventDefault()
                          move(message.id, queued[index + 2]?.id ?? null)
                        }
                      }}
                      className={cn(ACTION, 'w-6 cursor-grab active:cursor-grabbing')}
                    >
                      <GripIcon weight="bold" className="size-3.5" />
                    </button>
                  ) : null}
                  <span className="text-faint mx-1 text-[11.5px]">{formatTime(message.ts)}</span>
                </span>
                {editing ? (
                  <>
                    <span className="text-brand-strong px-1 text-[12px] font-medium">
                      Editing in the composer
                    </span>
                    <button type="button" onClick={onCancelEdit} className={cn(ACTION, 'px-2')}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      title={`${WORKING.has(status) ? 'Send into the running turn' : 'Start a turn with this message'}${index === 0 ? ' (Ctrl+Shift+Enter)' : ''}`}
                      disabled={moving}
                      onClick={() => actions.send(message.id)}
                      className={cn(ACTION, 'hover:text-brand-strong hover:bg-brand-soft px-2')}
                    >
                      <ArrowUpIcon weight="bold" className="size-3" />
                      Send now
                    </button>
                    {canEdit ? (
                      <button
                        type="button"
                        title={`Edit in the composer${index === queued.length - 1 ? ' (Alt+Up)' : ''}`}
                        aria-label="Edit queued message"
                        disabled={moving || editingId !== undefined}
                        onClick={() => onEdit(message)}
                        className={cn(ACTION, 'w-6')}
                      >
                        <PencilIcon className="size-3.5" />
                      </button>
                    ) : null}
                    <button
                      type="button"
                      title="Remove from queue"
                      aria-label="Remove queued message"
                      disabled={moving}
                      onClick={() => actions.remove(message.id)}
                      className={cn(ACTION, 'w-6')}
                    >
                      <XMarkIcon className="size-3.5" />
                    </button>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      {collapsible ? (
        <button
          type="button"
          aria-expanded={showAll}
          onClick={() => setShowAll((v) => !v)}
          className={cn(ACTION, 'px-2')}
        >
          {showAll ? 'Show fewer' : `Show all ${queued.length} queued`}
          <CaretDownIcon className={cn('size-3 transition-transform', showAll && 'rotate-180')} />
        </button>
      ) : null}
    </section>
  )
}
