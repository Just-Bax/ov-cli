import { ArrowTopRightOnSquareIcon, ClockIcon, TrashIcon } from '@heroicons/react/24/outline'
import { formatMinutes, savedMinutes } from '@shared/estimate.ts'
import { Composer } from '@/components/Composer'
import { EditableTitle } from '@/components/EditableTitle'
import { dialog } from '@/components/Dialog'
import { WriteSwitch } from '@/components/WriteSwitch'
import { useEffect, useRef, useState } from 'react'
import type { ChatMessage, Rating, RunState, ThreadItem, ToolActivity } from '@shared/types.ts'
import { StatusIcon } from '@/components/Sidebar'
import {
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
import { useSettings } from '@/lib/settings'
import { useRun } from '@/lib/useRun'
import { ChangeCard } from './ChangeCard'
import { FilesChanged, LineCounts, summarize } from './FilesChanged'
import { ThreadRail } from './ThreadRail'
import { AssistantActions, QueuedMessage, UserMessage } from './Messages'
import { Answer, LoginCard, QuestionCard } from './Panels'
import { ToolGroup } from './ToolGroup'

const FOLLOW_BOTTOM_PX = 80
const USER_SCROLL_MS = 600
const USER_SCROLL_EVENTS = ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const
const MARK_LABEL_CHARS = 160

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

function Footer({
  runId,
  busy,
  write,
  onSend,
}: {
  runId: string
  busy: boolean
  write: boolean
  onSend: () => void
}) {
  const [error, setError] = useState<string>()

  const send = async (text: string, files: File[] = []) => {
    setError(undefined)
    onSend()
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
  const { settings } = useSettings()
  const { state: loaded, error } = useRun(id)
  const [feedback, setFeedback] = useState<{ rating: Rating; note: string }>()
  const state = loaded && feedback ? { ...loaded, feedback } : loaded
  const scrollRef = useRef<HTMLDivElement>(null)
  const followBottom = useRef(true)
  const ready = Boolean(state)

  useEffect(() => {
    const content = scrollRef.current
    const scroller = content?.parentElement
    if (!content || !scroller) return

    let userScrolledAt = 0
    const pinToBottom = () => {
      if (followBottom.current) scroller.scrollTop = scroller.scrollHeight
    }
    const markUser = () => {
      userScrolledAt = Date.now()
    }
    const onScroll = () => {
      const fromBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
      if (fromBottom < FOLLOW_BOTTOM_PX) followBottom.current = true
      else if (Date.now() - userScrolledAt < USER_SCROLL_MS) followBottom.current = false
    }

    followBottom.current = true
    const contentGrowth = new ResizeObserver(pinToBottom)
    contentGrowth.observe(content)
    scroller.addEventListener('scroll', onScroll, { passive: true })
    for (const name of USER_SCROLL_EVENTS)
      scroller.addEventListener(name, markUser, { passive: true })
    pinToBottom()

    return () => {
      contentGrowth.disconnect()
      scroller.removeEventListener('scroll', onScroll)
      for (const name of USER_SCROLL_EVENTS) scroller.removeEventListener(name, markUser)
    }
  }, [ready])

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
            Case {summary.caseKey} <ArrowTopRightOnSquareIcon className="size-3" />
          </a>
        </>
      ) : null}
      {!busy && settings.showTimeSaved && state.outcome?.timeSaved ? (
        <>
          <Dot />
          <span
            title={state.outcome.timeSaved.basis}
            className={cn(
              'inline-flex cursor-help items-center gap-1 font-medium',
              savedMinutes(state) ? 'text-ok' : 'text-faint line-through',
            )}
          >
            <ClockIcon className="size-3" />~{formatMinutes(state.outcome.timeSaved.minutes)} saved
          </span>
        </>
      ) : null}
      {state.edits.length ? (
        <>
          <Dot />
          <span className="inline-flex items-center gap-1.5">
            {summarize(state.edits).length} file{summarize(state.edits).length === 1 ? '' : 's'}{' '}
            changed
            <LineCounts
              added={state.edits.reduce((n, e) => n + e.added, 0)}
              removed={state.edits.reduce((n, e) => n + e.removed, 0)}
            />
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
        <TrashIcon className="size-3.5" />
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
        <Footer
          runId={id}
          busy={busy}
          write={state.writeAccess}
          onSend={() => {
            followBottom.current = true
          }}
        />
      }
    >
      <ThreadRail
        contentRef={scrollRef}
        version={`${state.items.length}:${state.chat.length}:${state.tools.length}`}
        onJump={() => {
          followBottom.current = false
        }}
      />
      <div ref={scrollRef} className="mx-auto max-w-[860px] space-y-5 px-6 pt-6 pb-8">
        {turns.map((turn, i) => {
          const isLast = i === turns.length - 1
          const active = isLast && busy
          const text = turnText(turn, state)
          const toolIds = new Set(
            turn.blocks.flatMap((b) => (b.kind === 'tools' ? b.tools.map((x) => x.id) : [])),
          )
          const edits = state.edits.filter((e) => toolIds.has(e.toolId))
          const turnId = turn.user?.id
          const hasOutcome = turn.blocks.some(
            (b) => b.kind === 'item' && b.item.kind === 'outcome' && b.item.id === state.outcomeId,
          )

          return (
            <div key={turnId ?? `t${i}`} className="space-y-4">
              {turn.user ? (
                <div data-mark="user" data-label={turn.user.text.slice(0, MARK_LABEL_CHARS)}>
                  <UserMessage runId={id} message={turn.user} canRetry={!busy} />
                </div>
              ) : null}
              {turn.blocks.length ? (
                <div
                  data-mark="agent"
                  data-label={(text || 'Working').slice(0, MARK_LABEL_CHARS)}
                  className="space-y-4"
                >
                  {turn.blocks.map((b) => (
                    <ThreadBlock key={b.key} block={b} state={state} />
                  ))}
                  <FilesChanged edits={edits} />
                </div>
              ) : null}
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
        ))}
        {state.error && summary.status === 'error' ? (
          <div
            className={cn(
              'border-danger/40 bg-danger-soft/50 text-danger rounded-2xl border px-4 py-3 text-[13px]',
            )}
          >
            {state.error}
          </div>
        ) : null}
      </div>
    </Page>
  )
}
