import {
  ArrowBendUpRight as SteerIcon,
  CaretDown as CaretDownIcon,
  DotsSixVertical as GripIcon,
  FileText as DocumentTextIcon,
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

const ACTION =
  'text-faint hover:text-fg hover:bg-black/[0.06] flex h-6 shrink-0 items-center justify-center gap-1 rounded-full transition-colors disabled:pointer-events-none disabled:opacity-40'
const DROP_LINE = 'bg-brand pointer-events-none absolute inset-x-1 h-0.5 rounded-full'

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
      className="border-line-strong/80 relative mx-5 -mb-5 rounded-t-[20px] border border-b-0 bg-white px-2 pt-1.5 pb-6 shadow-[0_-2px_10px_rgba(38,50,56,0.04)]"
    >
      <div className="flex h-7 items-center gap-1.5 pr-1 pl-2.5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="text-muted hover:text-fg flex min-w-0 flex-1 items-center gap-1.5 text-[12px] font-medium"
        >
          Queued
          <span className="bg-raised text-text rounded-full px-1.5 text-[11px] leading-[18px] font-semibold tabular-nums">
            {queued.length}
          </span>
          {held ? (
            <span className="bg-warn-soft text-warn rounded-full px-2 text-[11px] leading-[18px] font-semibold">
              Paused
            </span>
          ) : null}
          <span className="flex-1" />
          <CaretDownIcon className={cn('size-3 transition-transform', !expanded && 'rotate-180')} />
        </button>
        {held && busy ? (
          <button
            type="button"
            title="Start the queue again after this turn"
            onClick={() => void api.resumeQueue(runId).catch(reportError)}
            className={cn(ACTION, 'text-brand-strong px-2 text-[12px] font-medium')}
          >
            <PlayIcon weight="fill" className="size-2.5" />
            Resume
          </button>
        ) : null}
      </div>
      {expanded ? (
        <ol className="max-h-44 scrollbar-thin overflow-y-auto">
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
                  'group relative flex h-8 items-center gap-1.5 rounded-xl pr-1 pl-0.5 text-[13px] transition-colors',
                  editing ? 'bg-brand-soft' : 'hover:bg-raised',
                  drag?.id === message.id && 'opacity-40',
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
                  className="text-faint hover:text-fg relative flex size-6 shrink-0 cursor-grab items-center justify-center rounded-md text-[11px] font-medium tabular-nums active:cursor-grabbing disabled:cursor-default"
                >
                  <span className="group-focus-within:opacity-0 group-hover:opacity-0">
                    {index + 1}
                  </span>
                  <GripIcon
                    weight="bold"
                    className="absolute size-3.5 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
                  />
                </button>
                {files.map((f) =>
                  f.kind === 'image' ? (
                    <img
                      key={f.name}
                      src={api.fileUrl(runId, f.name)}
                      alt={f.name}
                      title={f.name}
                      className="border-line size-5 shrink-0 rounded border object-cover"
                    />
                  ) : (
                    <span key={f.name} title={f.name} className="text-muted shrink-0">
                      <DocumentTextIcon className="size-3.5" />
                    </span>
                  ),
                )}
                <span
                  className={cn(
                    'min-w-0 flex-1 truncate',
                    editing ? 'text-brand-strong' : 'text-text',
                  )}
                  title={message.text}
                >
                  {message.text}
                </span>
                {editing ? (
                  <>
                    <span className="text-brand-strong shrink-0 text-[11.5px] font-medium">
                      Editing
                    </span>
                    <button
                      type="button"
                      onClick={onCancelEdit}
                      className={cn(ACTION, 'text-muted px-2 text-[12px] font-medium')}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
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
                        aria-label="Remove from queue"
                        disabled={moving}
                        onClick={() => void api.removeQueued(runId, message.id).catch(reportError)}
                        className={cn(ACTION, 'w-6')}
                      >
                        <XMarkIcon className="size-3.5" />
                      </button>
                    </div>
                    {message.steer ? (
                      <Shimmer tone="brand" className="shrink-0 px-2 text-[12px] font-medium">
                        Steering
                      </Shimmer>
                    ) : busy ? (
                      <button
                        type="button"
                        title={`Send into the running turn${index === 0 ? ' (Ctrl+Shift+Enter)' : ''}`}
                        disabled={moving}
                        onClick={() => void api.steerQueued(runId, message.id).catch(reportError)}
                        className={cn(
                          ACTION,
                          'text-muted hover:text-brand-strong hover:bg-brand-soft px-2 text-[12px] font-medium',
                        )}
                      >
                        <SteerIcon weight="bold" className="size-3" />
                        Steer
                      </button>
                    ) : null}
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
