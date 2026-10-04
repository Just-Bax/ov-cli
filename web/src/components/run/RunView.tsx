import { Clock, ExternalLink, RotateCcw, Trash2 } from 'lucide-react'
import { formatMinutes, savedMinutes } from '@shared/estimate.ts'
import { Composer } from '@/components/Composer'
import { EditableTitle } from '@/components/EditableTitle'
import { dialog } from '@/components/Dialog'
import { WriteSwitch } from '@/components/WriteSwitch'
import { useEffect, useRef, useState } from 'react'
import type { ChatMessage, Rating, RunState, ThreadItem, ToolActivity } from '@shared/types.ts'
import { StatusIcon } from '@/components/Sidebar'
import {
  Button,
  Dot,
  IconButton,
  Markdown,
  Page,
  Skeleton,
  SkeletonText,
  Spinner,
  type Tone,
} from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go } from '@/lib/route'
import { useRun } from '@/lib/useRun'
import { ChangeCard } from './ChangeCard'
import { AssistantActions, QueuedMessage, UserMessage } from './Messages'
import { Answer, LoginCard, QuestionCard } from './Panels'
import { ToolGroup } from './ToolGroup'

const TONE_TEXT: Record<Tone, string> = {
  brand: 'text-brand-strong',
  ok: 'text-ok',
  warn: 'text-warn',
  danger: 'text-danger',
  neutral: 'text-muted',
}

const STATUS: Record<RunState['summary']['status'], { text: string; tone: Tone }> = {
  queued: { text: 'Starting', tone: 'brand' },
  running: { text: 'Working', tone: 'brand' },
  waiting: { text: 'Needs you', tone: 'warn' },
  done: { text: 'Done', tone: 'ok' },
  error: { text: 'Failed', tone: 'danger' },
  cancelled: { text: 'Stopped', tone: 'neutral' },
}

type Block =
  | { kind: 'tools'; tools: ToolActivity[]; key: string }
  | { kind: 'item'; item: ThreadItem; key: string }

interface Turn {
  user?: ChatMessage
  blocks: Block[]
}

/** Group the thread into turns: a user message and everything the agent did in reply. */
function toTurns(state: RunState): Turn[] {
  const turns: Turn[] = [{ blocks: [] }]
  for (const item of state.items) {
    const turn = turns.at(-1)!
    if (item.kind === 'user') {
      const user = state.chat.find((m) => m.id === item.id)
      if (user) turns.push({ user, blocks: [] })
      continue
    }
    if (item.kind === 'tool') {
      const tool = state.tools.find((t) => t.id === item.id)
      if (!tool) continue
      const last = turn.blocks.at(-1)
      if (last?.kind === 'tools') last.tools.push(tool)
      else turn.blocks.push({ kind: 'tools', tools: [tool], key: `t_${item.id}` })
    } else {
      turn.blocks.push({ kind: 'item', item, key: `${item.kind}_${item.id}` })
    }
  }
  return turns.filter((t) => t.user || t.blocks.length)
}

/** Plain text of an agent turn, for the copy button. */
function turnText(turn: Turn, state: RunState): string {
  const parts: string[] = []
  for (const b of turn.blocks) {
    if (b.kind !== 'item') continue
    if (b.item.kind === 'text') {
      const t = state.chat.find((m) => m.id === b.item.id)?.text.trim()
      if (t) parts.push(t)
    } else if (b.item.kind === 'outcome' && b.item.id === state.outcomeId && state.outcome) {
      for (const i of state.outcome.issues) parts.push(`${i.title}: ${i.summary}`)
      if (state.outcome.reply) parts.push(state.outcome.reply)
    } else if (b.item.kind === 'change') {
      const ch = state.changes.find((x) => x.id === b.item.id)
      if (ch) parts.push(`${ch.title}\n${ch.after}`)
    }
  }
  return parts.join('\n\n')
}

function turnTime(turn: Turn, state: RunState): number | undefined {
  for (let i = turn.blocks.length - 1; i >= 0; i--) {
    const b = turn.blocks[i]
    if (b.kind === 'item' && b.item.kind === 'text')
      return state.chat.find((m) => m.id === b.item.id)?.ts
  }
  return undefined
}

function ThreadBlock({ block, state }: { block: Block; state: RunState }) {
  if (block.kind === 'tools') return <ToolGroup tools={block.tools} />
  const { item } = block
  const id = state.summary.id
  switch (item.kind) {
    case 'text': {
      const msg = state.chat.find((m) => m.id === item.id)
      if (!msg?.text.trim()) return null
      return (
        <div className="text-fg">
          <Markdown text={msg.text} />
        </div>
      )
    }
    case 'change': {
      const change = state.changes.find((c) => c.id === item.id)
      return change ? <ChangeCard change={change} /> : null
    }
    case 'question': {
      const q = state.questions.find((x) => x.id === item.id)
      return q ? <QuestionCard runId={id} question={q} /> : null
    }
    case 'login': {
      const l = state.logins.find((x) => x.id === item.id)
      return l ? <LoginCard runId={id} login={l} /> : null
    }
    case 'outcome':
      if (item.id !== state.outcomeId || !state.outcome) {
        return <div className="text-faint text-[12px]">Earlier answer, updated below.</div>
      }
      return <Answer outcome={state.outcome} caseUrl={state.caseUrl} />
    default:
      return null
  }
}

const SUGGESTIONS = [
  'Make the reply shorter',
  'Show the fix as a diff',
  'Check another instance too',
  'Explain the root cause',
]

function Footer({
  runId,
  busy,
  done,
  write,
}: {
  runId: string
  busy: boolean
  done: boolean
  write: boolean
}) {
  const [error, setError] = useState<string>()
  const send = async (text: string, files: File[] = []) => {
    setError(undefined)
    try {
      const uploaded = files.length ? await api.upload(files) : []
      await api.message(runId, text, uploaded)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <div className="px-6 pt-1 pb-4">
      <div className="mx-auto max-w-[860px]">
        {done ? (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => void send(s)}
                className="border-line-strong text-text hover:bg-raised h-7 rounded-full border px-3 text-[12px]"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}
        {error ? <div className="text-danger mb-1.5 text-[12px]">{error}</div> : null}
        <Composer
          busy={busy}
          queueWhileBusy
          allowFiles
          placeholder={
            busy
              ? 'Send a follow-up; it is picked up at the next step'
              : 'Ask a follow-up or give direction'
          }
          onSend={(text, files) => send(text, files)}
          onStop={() => void api.cancel(runId)}
          extras={<WriteSwitch value={write} onChange={(v) => api.setWriteAccess(runId, v)} />}
        />
      </div>
    </div>
  )
}
export function RunView({ id }: { id: string }) {
  const { state: loaded, error } = useRun(id)
  const [feedback, setFeedback] = useState<{ rating: Rating; note: string }>()
  const state = loaded && feedback ? { ...loaded, feedback } : loaded
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const count = state
    ? state.items.length +
      state.tools.length +
      state.queued.length +
      state.chat.reduce((n, m) => n + m.text.length, 0)
    : 0
  useEffect(() => {
    if (stick.current) bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [count])

  if (error)
    return (
      <Page title="Run not found" subtitle={<span className="text-danger">{error}</span>}>
        {null}
      </Page>
    )
  if (!state) {
    return (
      <Page
        title={<Skeleton className="h-4 w-80" />}
        subtitle={
          <>
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-3 w-24" />
          </>
        }
      >
        <div className="mx-auto max-w-[860px] space-y-5 px-6 py-6">
          <div className="flex justify-end">
            <Skeleton className="h-9 w-56 rounded-2xl" />
          </div>
          <Skeleton className="h-9 w-full rounded-full" />
          <SkeletonText lines={2} />
          <Skeleton className="h-9 w-full rounded-full" />
          <SkeletonText lines={4} />
        </div>
      </Page>
    )
  }

  const { summary } = state
  const busy = ['queued', 'running', 'waiting'].includes(summary.status)
  const status = STATUS[summary.status]
  const turns = toTurns(state)
  const lastBlock = turns.at(-1)?.blocks.at(-1)
  const showThinking =
    summary.status === 'running' &&
    !(lastBlock?.kind === 'tools' && lastBlock.tools.some((t) => t.status === 'running')) &&
    !(lastBlock?.kind === 'item' && lastBlock.item.kind === 'text')

  const rerun = async () => {
    const { id: next } = await api.startRun({ ...state.input, model: summary.model })
    go({ page: 'run', id: next })
  }

  const subtitle = (
    <>
      <span className={cn('inline-flex items-center gap-1.5 font-medium', TONE_TEXT[status.tone])}>
        <StatusIcon status={summary.status} className="size-3" detailed />
        {status.text}
      </span>
      {state.writeAccess ? (
        <>
          <Dot />
          <span className="text-warn font-medium">Changes allowed</span>
        </>
      ) : null}
      {summary.caseKey && state.caseUrl ? (
        <>
          <Dot />
          <a
            href={state.caseUrl}
            target="_blank"
            rel="noreferrer"
            className="text-brand-strong inline-flex items-center gap-1 hover:underline"
          >
            Case {summary.caseKey} <ExternalLink className="size-3" />
          </a>
        </>
      ) : null}
      {!busy && state.outcome?.timeSaved ? (
        <>
          <Dot />
          <span
            title={state.outcome.timeSaved.basis}
            className={cn(
              'inline-flex cursor-help items-center gap-1 font-medium',
              savedMinutes(state) ? 'text-ok' : 'text-faint line-through',
            )}
          >
            <Clock className="size-3" />~{formatMinutes(state.outcome.timeSaved.minutes)} saved
          </span>
        </>
      ) : null}
      {summary.instance ? (
        <>
          <Dot />
          <span>{summary.instance}</span>
        </>
      ) : null}
    </>
  )
  const actions = (
    <>
      {!busy ? (
        <Button variant="ghost" onClick={() => void rerun()} title={`Model: ${summary.model}`}>
          <RotateCcw className="size-3.5" /> Run again
        </Button>
      ) : null}
      <IconButton
        label="Delete run"
        onClick={async () => {
          if (
            !(await dialog.confirm({
              title: 'Delete this run?',
              body: 'The conversation, findings and proposed fixes for this run will be removed. This cannot be undone.',
              confirmLabel: 'Delete',
              tone: 'danger',
            }))
          )
            return
          await api.deleteRun(id)
          go({ page: 'home' })
        }}
      >
        <Trash2 className="size-3.5" />
      </IconButton>
    </>
  )

  return (
    <Page
      title={
        <EditableTitle
          value={summary.title}
          onSave={(title) => api.renameRun(id, title)}
          inputClassName="h-8 max-w-[640px] text-[15px] font-semibold"
        />
      }
      subtitle={subtitle}
      actions={actions}
      footer={
        <Footer runId={id} busy={busy} done={summary.status === 'done'} write={state.writeAccess} />
      }
    >
      <div
        ref={scrollRef}
        onWheel={(e) => {
          const el = e.currentTarget.parentElement
          if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
        }}
        className="mx-auto max-w-[860px] space-y-5 px-6 py-6"
      >
        {turns.map((turn, i) => {
          const isLast = i === turns.length - 1
          const active = isLast && busy
          const text = turnText(turn, state)
          const turnId = turn.user?.id
          const hasOutcome = turn.blocks.some(
            (b) => b.kind === 'item' && b.item.kind === 'outcome' && b.item.id === state.outcomeId,
          )
          return (
            <div key={turnId ?? `t${i}`} className="space-y-4">
              {turn.user ? <UserMessage runId={id} message={turn.user} canRetry={!busy} /> : null}
              {turn.blocks.map((b) => (
                <ThreadBlock key={b.key} block={b} state={state} />
              ))}
              {!active && turnId && text ? (
                <AssistantActions
                  runId={id}
                  turnId={turnId}
                  text={text}
                  ts={turnTime(turn, state)}
                  rating={state.ratings[turnId]}
                  canRetry={!busy}
                  onRated={(rating, note) => {
                    if (!hasOutcome) return
                    if (rating) {
                      setFeedback({ rating, note: note ?? '' })
                      void api.feedback(id, rating, note ?? '')
                    }
                  }}
                />
              ) : null}
            </div>
          )
        })}
        {showThinking ? (
          <div className="text-muted flex items-center gap-2 text-[12.5px]">
            <Spinner className="text-brand size-3.5" /> Thinking
          </div>
        ) : null}
        {state.queued.map((m) => (
          <QueuedMessage key={m.id} runId={id} message={m} />
        ))}{' '}
        {state.error && summary.status === 'error' ? (
          <div
            className={cn(
              'border-danger/40 bg-danger-soft/50 text-danger rounded-2xl border px-4 py-3 text-[13px]',
            )}
          >
            {state.error}
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>
    </Page>
  )
}
