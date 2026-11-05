import {
  ArrowsMerge,
  ArrowsSplit,
  type IconProps,
  SealCheck as FindingsIcon,
  PencilSimple as EditIcon,
  Trash as TrashIcon,
} from '@phosphor-icons/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Finding, Origin, RunSummary, ThreadLink } from '@shared/types.ts'
import { notifyAction, reportError } from '@/components/common/Toasts'
import { Button, SkeletonText, Textarea } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useClickOutside, useEnterTransition } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { go, href } from '@/lib/route'
import { allRuns, refreshRuns, useRuns } from '@/lib/runs'
import { HEADER_PILL } from './BrowserPane'
import { StatusIcon } from './RunStatus'

const TOAST_MS = 8000
const PANEL_WIDTH = 380
const PANEL_GAP = 6
const EDGE_PX = 8

const LINEAGE_LABEL: Record<Origin, string> = {
  branch: 'Branched from',
  summary: 'Continued from',
  findings: 'Started from the findings of',
}

const ORIGIN_NAME: Record<Origin, string> = {
  branch: 'Branch',
  summary: 'Continued',
  findings: 'From findings',
}

export function BranchIcon({ className, ...props }: IconProps) {
  return <ArrowsSplit className={cn('rotate-90', className)} {...props} />
}

export function BringBackIcon({ className, ...props }: IconProps) {
  return <ArrowsMerge className={cn('rotate-90', className)} {...props} />
}

export async function openThread(made: Promise<{ id: string }>): Promise<void> {
  const { id } = await made
  await refreshRuns()
  go({ page: 'thread', id })
}

export function startedAside(id: string): void {
  void refreshRuns()
  notifyAction('Aside started in a new branch', 'Open', () => go({ page: 'thread', id }), TOAST_MS)
}

export function LineageNote({ origin, parent }: { origin: Origin; parent?: ThreadLink | null }) {
  return (
    <div className="text-muted flex items-center gap-3 text-[12px]">
      <div className="bg-line h-px flex-1" />
      <span>
        {LINEAGE_LABEL[origin]}{' '}
        {parent ? (
          <a
            href={href({ page: 'thread', id: parent.id })}
            className="text-brand-strong font-medium hover:underline"
          >
            {parent.title}
          </a>
        ) : (
          'a deleted thread'
        )}
      </span>
      <div className="bg-line h-px flex-1" />
    </div>
  )
}

export function InheritedToggle({
  turns,
  open,
  onToggle,
}: {
  turns: number
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex justify-center">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="text-muted hover:text-fg hover:bg-raised rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
      >
        {open
          ? 'Hide the turns this branch came with'
          : `Show the ${turns} ${turns === 1 ? 'turn' : 'turns'} this branch came with`}
      </button>
    </div>
  )
}

function branchVersion(runs: RunSummary[], parentId: string): string {
  return runs
    .filter((r) => r.parentId === parentId)
    .map((r) => `${r.id}:${r.status}:${r.title}`)
    .join(',')
}

export function BranchList({ runId }: { runId: string }) {
  const list = useRuns()
  const version = branchVersion(allRuns(list), runId)
  const [branches, setBranches] = useState<RunSummary[]>([])

  useEffect(() => {
    let live = true
    api
      .branches(runId)
      .then((found) => live && setBranches(found.branches))
      .catch(reportError)
    return () => {
      live = false
    }
  }, [runId, version])

  if (!branches.length) return null

  return (
    <div className="border-line rounded-2xl border px-2 py-2">
      <div className="text-muted px-2 pb-1 text-[11.5px] font-medium">
        Threads started from this one
      </div>
      {branches.map((branch) => (
        <a
          key={branch.id}
          href={href({ page: 'thread', id: branch.id })}
          className="hover:bg-raised flex h-8 items-center gap-2 rounded-xl px-2 text-[12.5px] transition-colors"
        >
          <StatusIcon status={branch.status} className="size-3 shrink-0" detailed />
          <span className="text-fg min-w-0 flex-1 truncate">{branch.title}</span>
          {branch.origin ? (
            <span className="text-faint shrink-0 text-[11.5px]">{ORIGIN_NAME[branch.origin]}</span>
          ) : null}
        </a>
      ))}
    </div>
  )
}

export function BringBackDialog({
  runId,
  parent,
  onClose,
}: {
  runId: string
  parent: ThreadLink
  onClose: () => void
}) {
  const [text, setText] = useState<string>()
  const [error, setError] = useState<string>()
  const [sending, setSending] = useState(false)
  const shown = useEnterTransition(true)

  useLayer(onClose)

  useEffect(() => {
    let live = true
    api
      .bringBackDraft(runId)
      .then((draft) => live && setText(draft.text))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [runId])

  const send = async () => {
    setSending(true)
    setError(undefined)
    try {
      await api.bringBack(runId, text ?? '')
      notifyAction(
        `Brought back to ${parent.title}`,
        'Open',
        () => go({ page: 'thread', id: parent.id }),
        TOAST_MS,
      )
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSending(false)
    }
  }

  return createPortal(
    <div
      className={cn(
        'fixed inset-0 z-[100] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px] transition-opacity duration-200',
        shown ? 'opacity-100' : 'opacity-0',
      )}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Bring back to the parent thread"
        className={cn(
          'modal-enter w-full max-w-[560px] rounded-2xl bg-white p-5 shadow-[0_20px_60px_rgba(38,50,56,0.25)]',
          shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-3 scale-[0.98] opacity-0',
        )}
      >
        <div className="flex gap-3.5">
          <div className="bg-brand-soft flex size-10 shrink-0 items-center justify-center rounded-full">
            <BringBackIcon className="text-brand size-5" />
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">Bring back to {parent.title}</div>
            <div className="text-muted mt-1.5 text-[13px] leading-relaxed">
              The parent gets this note as context with its next message. It does not start a turn
              there. Edit it before you send.
            </div>
          </div>
        </div>
        <div className="mt-4">
          {text === undefined && !error ? (
            <SkeletonText lines={5} />
          ) : (
            <Textarea
              className="min-h-48 w-full"
              value={text ?? ''}
              onChange={(e) => setText(e.target.value)}
              aria-label="Note for the parent thread"
            />
          )}
          {error ? <div className="text-danger mt-2 text-[12px]">{error}</div> : null}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="lg" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="lg"
            busy={sending}
            disabled={sending || !text?.trim()}
            onClick={() => void send()}
          >
            Bring back
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function FindingRow({ runId, finding }: { runId: string; finding: Finding }) {
  const [editing, setEditing] = useState<string>()
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      await api.editFinding(runId, finding.id, editing ?? '')
      setEditing(undefined)
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  if (editing !== undefined)
    return (
      <div className="space-y-1.5 px-1 py-1">
        <Textarea
          className="min-h-16 w-full"
          value={editing}
          autoFocus
          onChange={(e) => setEditing(e.target.value)}
          aria-label="Edit finding"
        />
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setEditing(undefined)}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            busy={busy}
            disabled={busy || !editing.trim()}
            onClick={() => void save()}
          >
            Save
          </Button>
        </div>
      </div>
    )

  return (
    <div className="group/finding hover:bg-raised flex items-start gap-2 rounded-xl px-2 py-1.5">
      <span className="text-fg min-w-0 flex-1 text-[12.5px] leading-relaxed whitespace-pre-wrap">
        {finding.text}
      </span>
      <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover/finding:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          aria-label="Edit finding"
          title="Edit"
          onClick={() => setEditing(finding.text)}
          className="text-faint hover:text-fg flex size-6 items-center justify-center rounded-full"
        >
          <EditIcon className="size-3.5" />
        </button>
        <button
          type="button"
          aria-label="Delete finding"
          title="Delete"
          onClick={() => void api.deleteFinding(runId, finding.id).catch(reportError)}
          className="text-faint hover:text-danger flex size-6 items-center justify-center rounded-full"
        >
          <TrashIcon className="size-3.5" />
        </button>
      </div>
    </div>
  )
}

function FindingsPanel({ runId, findings }: { runId: string; findings: Finding[] }) {
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const [starting, setStarting] = useState(false)

  const add = async () => {
    setAdding(true)
    try {
      await api.addFinding(runId, draft)
      setDraft('')
    } catch (e) {
      reportError(e)
    } finally {
      setAdding(false)
    }
  }

  const start = () => {
    setStarting(true)
    openThread(api.fromFindings(runId))
      .catch(reportError)
      .finally(() => setStarting(false))
  }

  return (
    <div className="space-y-2">
      <div className="px-2 pt-1">
        <div className="text-fg text-[13px] font-semibold">Findings</div>
        <div className="text-muted text-[12px] leading-relaxed">
          Facts verified in this thread. Branches carry them, and a new thread can start from them.
        </div>
      </div>
      <div className="max-h-72 scrollbar-thin overflow-y-auto">
        {findings.length ? (
          findings.map((finding) => <FindingRow key={finding.id} runId={runId} finding={finding} />)
        ) : (
          <div className="text-faint px-2 py-2 text-[12.5px]">
            Nothing saved yet. The agent saves what it verifies here, and you can add your own.
          </div>
        )}
      </div>
      <div className="space-y-1.5 px-1">
        <Textarea
          className="min-h-16 w-full"
          value={draft}
          placeholder="Add a fact you checked"
          onChange={(e) => setDraft(e.target.value)}
          aria-label="New finding"
        />
        <div className="flex justify-between gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            className="gap-1.5"
            busy={starting}
            disabled={starting || !findings.length}
            onClick={start}
          >
            <BranchIcon className="size-3.5" />
            New thread from findings
          </Button>
          <Button
            size="sm"
            variant="primary"
            busy={adding}
            disabled={adding || !draft.trim()}
            onClick={() => void add()}
          >
            Add
          </Button>
        </div>
      </div>
    </div>
  )
}

export function FindingsButton({
  runId,
  version,
  open,
  onOpenChange,
}: {
  runId: string
  version: number
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [findings, setFindings] = useState<Finding[]>([])
  const [pos, setPos] = useState<{ left: number; top: number }>()
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const close = () => onOpenChange(false)

  useEffect(() => {
    let live = true
    api
      .findings(runId)
      .then((found) => live && setFindings(found.findings))
      .catch(reportError)
    return () => {
      live = false
    }
  }, [runId, version])

  useLayoutEffect(() => {
    const button = trigger.current
    if (!open || !button) {
      setPos(undefined)
      return
    }
    const box = button.getBoundingClientRect()
    const left = Math.min(
      Math.max(EDGE_PX, box.right - PANEL_WIDTH),
      window.innerWidth - PANEL_WIDTH - EDGE_PX,
    )
    setPos({ left, top: box.bottom + PANEL_GAP })
  }, [open])

  useClickOutside([panel, trigger], close, open)
  useLayer(close, open)

  if (!findings.length && !open) return null

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        title="Facts verified in this thread"
        onClick={() => onOpenChange(!open)}
        className={cn(HEADER_PILL, open && 'bg-line-strong/45')}
      >
        <FindingsIcon className="text-brand-strong size-3.5" />
        Findings
        {findings.length ? (
          <span className="text-muted tabular-nums">{findings.length}</span>
        ) : null}
      </button>
      {open && pos
        ? createPortal(
            <div
              ref={panel}
              style={{ left: pos.left, top: pos.top, width: PANEL_WIDTH }}
              className="border-line-strong/70 animate-pop fixed z-[200] rounded-2xl border bg-white p-2 shadow-[var(--shadow-large)]"
            >
              <FindingsPanel runId={runId} findings={findings} />
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
