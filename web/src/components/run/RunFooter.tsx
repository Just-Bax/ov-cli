import {
  ArrowBendUpRight as SteerIcon,
  ListNumbers as QueueIcon,
  Play as PlayIcon,
} from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type {
  Access,
  ChatMessage,
  ContextUsage,
  FollowUp,
  MessageFile,
  Provider,
  Question,
  RunStatus,
  RunSummary,
  ToolActivity,
} from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button } from '@/components/common/ui'
import { Composer, type ComposerKeyHandler } from '@/components/composer/Composer'
import { MENU_HINT, threadCommands, useAccessCommand } from '@/components/composer/commands'
import { AccessPicker } from '@/components/composer/AccessPicker'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { forgetDraft, loadText } from '@/lib/drafts'
import { fileOf, newMessageId, useApply } from '@/lib/optimistic'
import { useQueueActions } from '@/lib/queueActions'
import { patchLocally } from '@/lib/runs'
import { useProvider } from '@/lib/settings'
import { ContextMeter, FreshBranchNotice, StaleCacheNotice } from './Context'
import { sentFile } from './FilePreview'
import { QuestionComposer } from './QuestionDock'
import { ParkedNotice } from './RunMenu'

export type QueuedEdit = ReturnType<typeof useQueuedEdit>

const FOLLOW_UP_HINT: Record<FollowUp, string> = {
  queue: 'Queue: sent as its own turn after this one',
  steer: 'Steer: sent into the running turn',
}

export function useQueuedEdit(runId: string, queued: ChatMessage[]) {
  const [editing, setEditing] = useState<ChatMessage>()
  const [kept, setKept] = useState<MessageFile[]>([])
  const [draft, setDraft] = useState<{ text: string; at: number }>()
  const runKey = `run-${runId}`
  const editKey = editing ? `queued-${editing.id}` : runKey

  const startEdit = (message: ChatMessage) => {
    setEditing(message)
    setKept(message.files ?? [])
    setDraft({ text: message.text, at: Date.now() })
  }

  const endEdit = () => {
    forgetDraft(editKey)
    setEditing(undefined)
  }

  useEffect(() => {
    if (!editing || queued.some((m) => m.id === editing.id)) return
    const edited = loadText(editKey)
    endEdit()
    if (edited.trim() && edited !== editing.text && !loadText(runKey).trim())
      setDraft({ text: edited, at: Date.now() })
  }, [queued, editing])

  return { editing, kept, setKept, draft, startEdit, endEdit, editKey }
}

export function RunFooter({
  runId,
  provider,
  idleSince,
  run,
  settled,
  busy,
  status,
  access,
  context,
  compact,
  question,
  tool,
  queued,
  queueHeld,
  freshBranchTurns,
  edit,
  history,
  onStop,
  onSend,
}: {
  runId: string
  provider: Provider
  idleSince: number
  run: RunSummary
  settled: boolean
  busy: boolean
  status: RunStatus
  access: Access
  context?: ContextUsage
  compact: boolean
  question?: Question
  tool?: ToolActivity
  queued: ChatMessage[]
  queueHeld: boolean
  freshBranchTurns: number
  edit: QueuedEdit
  history: string[]
  onStop: () => void
  onSend: () => void
}) {
  const apply = useApply()
  const queue = useQueueActions(runId, queued, status)
  const { cacheTtlMs } = useProvider(provider)
  const [error, setError] = useState<string>()
  const { editing, kept, setKept, draft, startEdit, endEdit, editKey } = edit
  const modeFor = (alternate: boolean): FollowUp => (alternate ? 'steer' : 'queue')
  const parked = settled || Boolean(run.snoozedUntil)

  const send = async (text: string, files: File[], alternate: boolean) => {
    setError(undefined)

    try {
      if (editing) {
        await saveEdit(editing, text, files)
        return
      }

      onSend()
      await sendFollowUp(text, files, modeFor(alternate))
    } catch (e) {
      setError((e as Error).message)
      throw e
    }
  }

  const saveEdit = async (original: ChatMessage, text: string, files: File[]) => {
    const edited = { ...original, text, files: [...kept, ...files.map(fileOf)] }
    apply({ type: 'queue_add', message: edited })

    try {
      const uploaded = files.length ? await api.upload(files) : []
      await api.editQueued(
        runId,
        original.id,
        text,
        kept.map((f) => f.name),
        uploaded,
      )
    } catch (e) {
      apply({ type: 'queue_add', message: original })
      throw e
    }

    endEdit()
  }

  const sendFollowUp = async (text: string, files: File[], mode: FollowUp) => {
    const message: ChatMessage = {
      id: newMessageId(),
      role: 'user',
      text,
      ts: Date.now(),
      files: files.map(fileOf),
    }

    const steering = busy && mode === 'steer'
    if (steering) apply({ type: 'user_message', message: { ...message, steer: true } })
    else if (busy) apply({ type: 'queue_add', message })
    else {
      apply({ type: 'user_message', message })
      apply({ type: 'status', status: 'running' })
      patchLocally(runId, { status: 'running' })
    }

    try {
      const uploaded = files.length ? await api.upload(files) : []
      await api.message(runId, message.id, text, uploaded, mode)
    } catch (e) {
      if (steering) apply({ type: 'rewind', itemId: message.id })
      else if (busy) apply({ type: 'queue_remove', id: message.id })
      else {
        apply({ type: 'rewind', itemId: message.id })
        apply({ type: 'status', status })
      }
      throw e
    }
  }

  const shortcut: ComposerKeyHandler = (e, at) => {
    if (editing && e.key === 'Escape') {
      endEdit()
      return true
    }

    const oldest = queued[0]
    if (e.key === 'Enter' && e.shiftKey && (e.ctrlKey || e.metaKey) && busy && oldest) {
      queue.send(oldest.id)
      return true
    }

    const latest = queued.at(-1)
    if (e.key !== 'ArrowUp' || !e.altKey || !at.start || editing || !latest) return false

    startEdit(latest)
    return true
  }

  const pickAccess = (next: Access) => {
    apply({ type: 'access', access: next })
    api.setAccess(runId, next).catch((e: unknown) => {
      apply({ type: 'access', access })
      reportError(e)
    })
  }

  const commands = [...threadCommands(run, settled, busy, onStop), useAccessCommand(pickAccess)]

  const extras = (
    <>
      <AccessPicker value={access} onChange={pickAccess} />
      {context ? <ContextMeter runId={runId} context={context} busy={busy} /> : null}
    </>
  )

  return (
    <div className={cn('pt-1 pb-4', compact ? 'px-4' : 'px-6')}>
      <div className="mx-auto max-w-[860px]">
        {error ? <div className="text-danger mb-1.5 text-[12px]">{error}</div> : null}
        {!busy && !question ? <ParkedNotice run={run} settled={settled} /> : null}
        {freshBranchTurns && !busy && !question && !parked ? (
          <FreshBranchNotice runId={runId} turns={freshBranchTurns} context={context} />
        ) : null}
        {context && cacheTtlMs && !busy && !question && !parked && !freshBranchTurns ? (
          <StaleCacheNotice
            runId={runId}
            context={context}
            idleSince={idleSince}
            cacheTtlMs={cacheTtlMs}
          />
        ) : null}
        {question ? (
          <QuestionComposer
            runId={runId}
            question={question}
            tool={tool}
            busy={busy}
            extras={extras}
            onStop={onStop}
          />
        ) : (
          <div className="relative">
            <Composer
              busy={busy}
              queueWhileBusy
              allowFiles
              sentFiles={editing ? kept.map((file) => sentFile(runId, file)) : undefined}
              onRemoveSentFile={(name) => setKept((files) => files.filter((f) => f.name !== name))}
              placeholder={
                editing
                  ? 'Edit the queued message. Enter saves, Escape cancels'
                  : busy
                    ? `${FOLLOW_UP_HINT.queue}. Ctrl+Enter to steer`
                    : `Ask a follow-up or give direction. ${MENU_HINT}`
              }
              busyAction={(alternate) => {
                const mode = modeFor(alternate)
                return {
                  label: FOLLOW_UP_HINT[mode],
                  icon:
                    mode === 'steer' ? (
                      <SteerIcon weight="bold" className="size-4" />
                    ) : (
                      <QueueIcon weight="bold" className="size-4" />
                    ),
                }
              }}
              idleAction={
                queueHeld && queued.length ? (
                  <Button variant="primary" onClick={queue.resume}>
                    <PlayIcon weight="fill" className="size-3" />
                    Resume
                  </Button>
                ) : undefined
              }
              submitLabel={editing ? () => 'Save' : undefined}
              onKeyDown={shortcut}
              commands={commands}
              instance={run.instance}
              runId={runId}
              history={history}
              onSend={send}
              draft={draft}
              draftKey={editKey}
              onStop={onStop}
              extras={extras}
            />
          </div>
        )}
      </div>
    </div>
  )
}
