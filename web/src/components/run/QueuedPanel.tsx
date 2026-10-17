import {
  ArrowBendUpRight as SteerIcon,
  CaretDown as CaretDownIcon,
  DotsSixVertical as GripIcon,
  FileText as DocumentTextIcon,
  ListNumbers as QueueIcon,
  PencilSimple as PencilIcon,
  Play as PlayIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import type { ChatMessage } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Shimmer } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

const ROW_ACTION =
  'text-muted hover:bg-black/[0.06] hover:text-fg flex h-7 shrink-0 items-center justify-center gap-1 rounded-full transition-colors disabled:pointer-events-none disabled:opacity-45'
const DROP_LINE = 'bg-brand pointer-events-none absolute inset-x-2 h-0.5 rounded-full'

type Drag = { id: string; insert: number | null }

export function QueuedPanel({
  runId,
  queued,
  held,
  busy,
  editingId,
  canEdit,
  onEdit,
  onCancelEdit,
}: {
  runId: string
  queued: ChatMessage[]
  held: boolean
  busy: boolean
  editingId?: string
  canEdit: boolean
  onEdit: (message: ChatMessage) => void
  onCancelEdit: () => void
}) {
  const [expanded, setExpanded] = useState(true)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [moving, setMoving] = useState(false)
  const armed = useRef<string | null>(null)
  if (!queued.length) return null

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
    <div
      role="region"
      aria-label={`${queued.length} queued message${queued.length === 1 ? '' : 's'}`}
      className="border-line-strong bg-canvas relative mx-4 -mb-6 rounded-t-[22px] border border-b-0 px-3 pt-2 pb-7"
    >
      <div className="flex h-7 items-center gap-2 px-1 text-[12.5px]">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="text-muted hover:text-fg flex min-w-0 flex-1 items-center gap-2"
        >
          <QueueIcon className="size-3.5 shrink-0" />
          <span className="font-medium">Queued</span>
          {held ? <span className="text-warn">Paused</span> : null}
          <span className="flex-1" />
          <span className="text-fg font-semibold tabular-nums">{queued.length}</span>
          <CaretDownIcon
            className={cn('size-3.5 transition-transform', !expanded && 'rotate-180')}
          />
        </button>
        {held ? (
          <button
            type="button"
            title="Start the queue again"
            onClick={() => void api.resumeQueue(runId).catch(reportError)}
            className={cn(ROW_ACTION, 'text-brand-strong px-2 font-medium')}
          >
            <PlayIcon weight="fill" className="size-3" />
            Resume
          </button>
        ) : null}
      </div>
      {expanded ? (
        <ol className="max-h-48 scrollbar-thin overflow-y-auto">
          {queued.map((message, index) => {
            const editing = message.id === editingId
            const files = message.files ?? []

            return (
              <li
                key={message.id}
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
                  'relative flex min-h-9 items-center gap-1.5 rounded-xl pr-1 text-[13px]',
                  editing && 'bg-brand-soft',
                  drag?.id === message.id && 'opacity-50',
                )}
              >
                {drag?.insert === index ? <span className={cn(DROP_LINE, 'top-0')} /> : null}
                {index === queued.length - 1 && drag?.insert === queued.length ? (
                  <span className={cn(DROP_LINE, 'bottom-0')} />
                ) : null}
                <button
                  type="button"
                  aria-label="Reorder queued message (drag, or press the arrow keys)"
                  disabled={moving || queued.length < 2}
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
                  className={cn(ROW_ACTION, 'w-5 cursor-grab active:cursor-grabbing')}
                >
                  <GripIcon weight="bold" className="size-3.5" />
                </button>
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
                <span className="text-fg min-w-0 flex-1 truncate" title={message.text}>
                  {message.text}
                </span>
                {editing ? (
                  <button
                    type="button"
                    onClick={onCancelEdit}
                    className={cn(ROW_ACTION, 'px-2 text-[12.5px] font-medium')}
                  >
                    Cancel
                  </button>
                ) : (
                  <>
                    {canEdit ? (
                      <button
                        type="button"
                        title={`Edit in the composer${index === queued.length - 1 ? ' (Alt+Up)' : ''}`}
                        aria-label="Edit queued message"
                        disabled={moving || editingId !== undefined}
                        onClick={() => onEdit(message)}
                        className={cn(ROW_ACTION, 'w-7')}
                      >
                        <PencilIcon className="size-3.5" />
                      </button>
                    ) : null}
                    {message.steer ? (
                      <Shimmer tone="brand" className="shrink-0 px-2 text-[12.5px] font-medium">
                        Steering
                      </Shimmer>
                    ) : (
                      <button
                        type="button"
                        title={
                          busy
                            ? `Send as a steer instead${index === 0 ? ' (Ctrl+Shift+Enter)' : ''}`
                            : 'There is no running turn to steer'
                        }
                        disabled={!busy || moving}
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
                      disabled={moving}
                      onClick={() => void api.removeQueued(runId, message.id).catch(reportError)}
                      className={cn(ROW_ACTION, 'w-7')}
                    >
                      <XMarkIcon className="size-3.5" />
                    </button>
                  </>
                )}
              </li>
            )
          })}
        </ol>
      ) : null}
    </div>
  )
}
