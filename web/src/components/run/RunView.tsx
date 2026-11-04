import {
  ArrowBendUpRight as SteerIcon,
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  ListNumbers as QueueIcon,
  Play as PlayIcon,
  ShieldWarning as ShieldWarningIcon,
} from '@phosphor-icons/react'
import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type {
  Access,
  ChatMessage,
  ApprovalQuestion,
  ContextUsage,
  FollowUp,
  Provider,
  Question,
  RunState,
  RunStatus,
  RunSummary,
  ThreadItem,
  ThreadLink as ThreadLinkTarget,
  ToolActivity,
} from '@shared/types.ts'
import { EditableTitle } from '@/components/common/EditableTitle'
import { ActionsSkeleton, ComposerSkeleton, useSkeleton } from '@/components/common/skeletons'
import { reportError } from '@/components/common/Toasts'
import {
  Button,
  Dot,
  Markdown,
  Page,
  Shimmer,
  Skeleton,
  SkeletonText,
  type Tone,
} from '@/components/common/ui'
import { Composer } from '@/components/composer/Composer'
import { AccessPicker } from '@/components/composer/AccessPicker'
import { OPEN_FIND } from '@/components/layout/CommandPalette'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { forgetDraft, loadText } from '@/lib/drafts'
import { inCodeEditor } from '@/lib/dom'
import { usePresence, useWindowEvent } from '@/lib/hooks'
import { layerOpen } from '@/lib/layers'
import { href } from '@/lib/route'
import { allRuns, patchLocally, useRuns, WORKING } from '@/lib/runs'
import { useProvider } from '@/lib/settings'
import { useRun } from '@/lib/useRun'
import { ChangeCard } from './ChangeCard'
import { GridCard } from './GridCard'
import { CompactionNote, ContextMeter, StaleCacheNotice } from './Context'
import { CostPill } from './CostPill'
import { FilesChanged } from './FilesChanged'
import { FIND_LABEL, FindBar } from './FindBar'
import { InstanceChips } from './InstanceChip'
import {
  BrowserBackdrop,
  BrowserPane,
  CARD_CLASS,
  CHAT_CARD_STYLE,
  isBrowserTool,
  OpenBrowserButton,
  ShowBrowserButton,
} from './BrowserPane'
import { AssistantActions, UserMessage } from './Messages'
import { Answer, LoginCard } from './Panels'
import { Reasoning } from '@/components/run/Reasoning'
import { useQueueActions } from '@/lib/queueActions'
import { ApplyContext, fileOf, newMessageId, stopEvents, useApply } from '@/lib/optimistic'
import { QueuedMessages } from './QueuedMessages'
import { AnsweredQuestion, QuestionComposer } from './QuestionDock'
import { ParkedNotice, RunMenu } from './RunMenu'
import { RUN_STATUS, StatusIcon } from './RunStatus'
import { ThreadRail } from './ThreadRail'
import { summarize, ToolGroup } from './ToolGroup'
import { Worked } from './Worked'

const FOLLOW_BOTTOM_PX = 80
const USER_SCROLL_MS = 600
const USER_SCROLL_EVENTS = ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const
const MARK_LABEL_CHARS = 160
const BROWSER_EXIT_MS = 200
const OLDER_MARGIN_PX = 600
const OLDER_ARM_MS = 500
const RUN_ACTION_WIDTHS = ['w-24', 'w-9']
const NOTHING_SPENT = { amount: 0, requests: 0 }

const MemoChangeCard = memo(ChangeCard)
const MemoGridCard = memo(GridCard)
const MemoAnswer = memo(Answer)
const MemoUserMessage = memo(UserMessage)

const TONE_TEXT: Record<Tone, string> = {
  brand: 'text-brand-strong',
  ok: 'text-ok',
  warn: 'text-warn',
  danger: 'text-danger',
  neutral: 'text-muted',
}

const LIVE_QUESTION = new Set(['running', 'waiting'])

type Block =
  | { kind: 'tools'; tools: ToolActivity[]; key: string }
  | { kind: 'item'; item: ThreadItem; key: string }

interface Turn {
  user?: ChatMessage
  start: number
  blocks: Block[]
}

function indexed<T extends { id: string }>(cache: WeakMap<T[], Map<string, T>>, list: T[]) {
  const found = cache.get(list)
  if (found) return found
  const made = new Map(list.map((x) => [x.id, x]))
  cache.set(list, made)
  return made
}

const chatIndex = new WeakMap<ChatMessage[], Map<string, ChatMessage>>()
const changeIndex = new WeakMap<RunState['changes'], Map<string, RunState['changes'][number]>>()
const turnCache = new WeakMap<ThreadItem[], { chat: unknown; tools: unknown; turns: Turn[] }>()

function chatById(state: RunState) {
  return indexed(chatIndex, state.chat)
}

function toTurns(state: RunState): Turn[] {
  const cached = turnCache.get(state.items)
  if (cached && cached.chat === state.chat && cached.tools === state.tools) return cached.turns
  const turns = buildTurns(state)
  turnCache.set(state.items, { chat: state.chat, tools: state.tools, turns })
  return turns
}

function buildTurns(state: RunState): Turn[] {
  const chat = chatById(state)
  const tools = new Map(state.tools.map((t) => [t.id, t]))
  const turns: Turn[] = [{ start: state.start, blocks: [] }]
  for (const [index, item] of state.items.entries()) {
    const turn = turns.at(-1)!
    if (item.kind === 'user') {
      const user = chat.get(item.id)
      if (user) turns.push({ user, start: state.start + index, blocks: [] })
      continue
    }

    if (item.kind === 'tool') {
      const tool = tools.get(item.id)
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

const RESULT_ITEMS = new Set<ThreadItem['kind']>(['change', 'grid', 'outcome', 'compact'])

function turnKeys(turn: Turn): string[] {
  return [...(turn.user ? [turn.user.id] : []), ...turn.blocks.map((b) => b.key)]
}

function useArrivedLive(state: RunState | undefined): (turn: Turn, key: string) => boolean {
  const opened = useRef<{ from: number; keys: Set<string> }>(undefined)
  if (state && !opened.current) {
    const last = toTurns(state).at(-1)
    opened.current = { from: last?.start ?? state.start, keys: new Set(last ? turnKeys(last) : []) }
  }

  return (turn, key) =>
    opened.current !== undefined &&
    turn.start >= opened.current.from &&
    !opened.current.keys.has(key)
}

function splitTurn(blocks: Block[]): { work: Block[]; result: Block[] } {
  const lastTools = blocks.findLastIndex((b) => b.kind === 'tools')
  if (lastTools < 0) return { work: [], result: blocks }

  const lastText = blocks.findLastIndex((b) => b.kind === 'item' && b.item.kind === 'text')
  const cut = lastText > lastTools || lastText < 0 ? lastTools + 1 : lastText
  const done = blocks.slice(0, cut)
  const kept = (b: Block) => b.kind === 'item' && RESULT_ITEMS.has(b.item.kind)

  return {
    work: done.filter((b) => !kept(b)),
    result: [...done.filter(kept), ...blocks.slice(cut)],
  }
}

function workSummary(work: Block[], state: RunState): string {
  const tools = work.flatMap((b) => (b.kind === 'tools' ? b.tools : []))

  const updates = work.filter(
    (b) =>
      b.kind === 'item' && b.item.kind === 'text' && chatById(state).get(b.item.id)?.text.trim(),
  ).length

  const said = updates ? [`${updates} ${updates === 1 ? 'update' : 'updates'}`] : []
  return [summarize(tools), ...said].filter(Boolean).join(', ')
}

function turnSpan(turn: Turn, state: RunState): number | undefined {
  const tools = turn.blocks.flatMap((b) => (b.kind === 'tools' ? b.tools : []))
  const texts = turn.blocks.flatMap((b) =>
    b.kind === 'item' && b.item.kind === 'text' ? [chatById(state).get(b.item.id)?.ts ?? 0] : [],
  )

  const starts = tools.flatMap((t) => (t.startedAt ? [t.startedAt] : []))
  const start = turn.user?.ts ?? Math.min(...starts, ...texts.filter(Boolean))
  const end = Math.max(...texts, ...tools.map((t) => (t.startedAt ?? 0) + (t.ms ?? 0)))
  return Number.isFinite(start) && end > start ? end - start : undefined
}

function blocksText(blocks: Block[], state: RunState): string {
  const parts: string[] = []
  for (const b of blocks) {
    if (b.kind !== 'item') continue

    if (b.item.kind === 'text') {
      const t = chatById(state).get(b.item.id)?.text.trim()
      if (t) parts.push(t)
    } else if (b.item.kind === 'outcome' && b.item.id === state.outcomeId && state.outcome) {
      for (const i of state.outcome.issues) parts.push(`${i.title}: ${i.summary}`)
      if (state.outcome.reply) parts.push(state.outcome.reply)
    } else if (b.item.kind === 'grid') {
      const grid = state.grids.find((g) => g.id === b.item.id)
      if (grid) parts.push(grid.title)
    } else if (b.item.kind === 'change') {
      const ch = indexed(changeIndex, state.changes).get(b.item.id)
      if (ch) parts.push(`${ch.title}\n${ch.after}`)
    }
  }

  return parts.join('\n\n')
}

function turnTime(turn: Turn, state: RunState): number | undefined {
  for (let i = turn.blocks.length - 1; i >= 0; i--) {
    const b = turn.blocks[i]
    if (b.kind === 'item' && b.item.kind === 'text') return chatById(state).get(b.item.id)?.ts
  }

  return undefined
}

function isOpen(question: Question): boolean {
  return !question.answers && !question.stopped
}

function browserQuestion(state: RunState): ApprovalQuestion | undefined {
  if (!state.browser?.open || !LIVE_QUESTION.has(state.summary.status)) return undefined

  const tools = new Map(state.tools.map((t) => [t.id, t.name]))

  return state.questions.find(
    (q): q is ApprovalQuestion =>
      q.kind === 'approval' &&
      isOpen(q) &&
      Boolean(q.toolId) &&
      isBrowserTool(tools.get(q.toolId ?? '')),
  )
}

function dockedQuestion(state: RunState): Question | undefined {
  if (!LIVE_QUESTION.has(state.summary.status)) return undefined

  const inBrowser = browserQuestion(state)?.id
  return state.questions.find((q) => isOpen(q) && q.id !== inBrowser)
}

function browserShown(state: RunState | undefined, hiddenSession: number | undefined): boolean {
  if (!state?.browser?.open) return false
  return state.browser.session !== hiddenSession || Boolean(browserQuestion(state))
}

function ThreadBlock({ block, state }: { block: Block; state: RunState }) {
  if (block.kind === 'tools') return <ToolGroup runId={state.summary.id} tools={block.tools} />

  const { item } = block
  const id = state.summary.id
  switch (item.kind) {
    case 'text': {
      const msg = chatById(state).get(item.id)
      const said = msg?.text.trim()
      const thought = msg?.reasoning?.trim()
      if (!msg || (!said && !thought)) return null

      return (
        <div className="text-fg space-y-2">
          {thought ? <Reasoning text={thought} /> : null}
          {said ? <Markdown text={msg.text} links={msg.links} /> : null}
        </div>
      )
    }
    case 'change': {
      const change = indexed(changeIndex, state.changes).get(item.id)
      return change ? <MemoChangeCard change={change} /> : null
    }
    case 'grid': {
      const grid = state.grids.find((g) => g.id === item.id)
      return grid ? <MemoGridCard grid={grid} runId={id} /> : null
    }
    case 'question': {
      const q = state.questions.find((x) => x.id === item.id)
      if (!q) return null

      const live = LIVE_QUESTION.has(state.summary.status)
      if (!isOpen(q) || !live) return <AnsweredQuestion question={q} />

      return (
        <div className="text-warn flex items-center gap-2 text-[12.5px] font-medium">
          <ShieldWarningIcon className="size-4" />
          {q.id === browserQuestion(state)?.id
            ? 'Waiting for your approval in the browser'
            : q.kind === 'approval'
              ? 'Waiting for your approval below'
              : 'Waiting for your answer below'}
        </div>
      )
    }
    case 'login': {
      const l = state.logins.find((x) => x.id === item.id)
      return l ? <LoginCard runId={id} login={l} /> : null
    }
    case 'outcome':
      if (item.id !== state.outcomeId || !state.outcome) {
        return <div className="text-faint text-[12px]">Earlier answer, updated below.</div>
      }

      return <MemoAnswer outcome={state.outcome} caseUrl={state.caseUrl} />
    case 'compact': {
      const compaction = state.compactions.find((c) => c.id === item.id)
      return compaction ? <CompactionNote compaction={compaction} /> : null
    }
    default:
      return null
  }
}

type QueuedEdit = ReturnType<typeof useQueuedEdit>

const NO_MESSAGES: ChatMessage[] = []

function useQueuedEdit(runId: string, queued: ChatMessage[]) {
  const [editing, setEditing] = useState<ChatMessage>()
  const [draft, setDraft] = useState<{ text: string; at: number }>()
  const runKey = `run-${runId}`
  const editKey = editing ? `queued-${editing.id}` : runKey

  const startEdit = (message: ChatMessage) => {
    setEditing(message)
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

  return { editing, setEditing, draft, startEdit, endEdit, editKey }
}

const FOLLOW_UP_HINT: Record<FollowUp, string> = {
  queue: 'Queue: sent as its own turn after this one',
  steer: 'Steer: sent into the running turn',
}

function Footer({
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
  edit,
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
  edit: QueuedEdit
  onStop: () => void
  onSend: () => void
}) {
  const apply = useApply()
  const queue = useQueueActions(runId, queued, status)
  const { cacheTtlMs } = useProvider(provider)
  const [error, setError] = useState<string>()
  const { editing, setEditing, draft, startEdit, endEdit, editKey } = edit
  const modeFor = (alternate: boolean): FollowUp => (alternate ? 'steer' : 'queue')
  const parked = settled || Boolean(run.snoozedUntil)

  const send = async (text: string, files: File[], alternate: boolean) => {
    setError(undefined)

    try {
      if (editing) {
        const original = editing
        apply({ type: 'queued', message: { ...original, text } })
        setEditing(undefined)
        await api.editQueued(runId, original.id, text).catch((e: unknown) => {
          apply({ type: 'queued', message: original })
          throw e
        })
        return
      }

      onSend()
      await sendFollowUp(text, files, modeFor(alternate))
    } catch (e) {
      setError((e as Error).message)
      throw e
    }
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
    if (steering) apply({ type: 'user', message: { ...message, steer: true } })
    else if (busy) apply({ type: 'queued', message })
    else {
      apply({ type: 'user', message })
      apply({ type: 'status', status: 'running' })
      patchLocally(runId, { status: 'running' })
    }

    try {
      const uploaded = files.length ? await api.upload(files) : []
      await api.message(runId, message.id, text, uploaded, mode)
    } catch (e) {
      if (steering) apply({ type: 'rewind', itemId: message.id })
      else if (busy) apply({ type: 'unqueue', id: message.id })
      else {
        apply({ type: 'rewind', itemId: message.id })
        apply({ type: 'status', status })
      }
      throw e
    }
  }

  const shortcut = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (editing && e.key === 'Escape') {
      endEdit()
      return true
    }

    const oldest = queued[0]
    if (e.key === 'Enter' && e.shiftKey && (e.ctrlKey || e.metaKey) && busy && oldest) {
      queue.send(oldest.id)
      return true
    }

    const atStart = e.currentTarget.selectionStart === 0 && e.currentTarget.selectionEnd === 0
    const latest = queued.at(-1)
    if (e.key !== 'ArrowUp' || !e.altKey || !atStart || editing || !latest) return false

    startEdit(latest)
    return true
  }

  const stop = onStop
  const pickAccess = (next: Access) => {
    apply({ type: 'access', access: next })
    api.setAccess(runId, next).catch((e: unknown) => {
      apply({ type: 'access', access })
      reportError(e)
    })
  }

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
        {context && cacheTtlMs && !busy && !question && !parked ? (
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
            onStop={stop}
          />
        ) : (
          <div className="relative">
            <Composer
              busy={busy}
              queueWhileBusy
              allowFiles={!editing}
              placeholder={
                editing
                  ? 'Edit the queued message. Enter saves, Escape cancels'
                  : busy
                    ? `${FOLLOW_UP_HINT.queue}. Ctrl+Enter to steer`
                    : 'Ask a follow-up or give direction'
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
              onSend={send}
              draft={draft}
              draftKey={editKey}
              onStop={stop}
              extras={extras}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function ThreadLink({ label, link }: { label: string; link: ThreadLinkTarget }) {
  return (
    <div className="text-muted flex items-center gap-3 text-[12px]">
      <div className="bg-line h-px flex-1" />
      <span>
        {label}{' '}
        <a
          href={href({ page: 'thread', id: link.id })}
          className="text-brand-strong font-medium hover:underline"
        >
          {link.title}
        </a>
      </span>
      <div className="bg-line h-px flex-1" />
    </div>
  )
}

function OlderTurns({
  scrollRef,
  start,
  loading,
  onVisible,
}: {
  scrollRef: React.RefObject<HTMLDivElement | null>
  start: number
  loading: boolean
  onVisible: () => Promise<void>
}) {
  const sentinel = useRef<HTMLDivElement>(null)
  const showSkeleton = useSkeleton(loading)

  useEffect(() => {
    const el = sentinel.current
    const root = scrollRef.current?.parentElement
    if (!el || !root) return

    let observer: IntersectionObserver | undefined
    const arm = setTimeout(() => {
      observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) void onVisible()
        },
        { root, rootMargin: `${OLDER_MARGIN_PX}px 0px 0px 0px` },
      )
      observer.observe(el)
    }, OLDER_ARM_MS)

    return () => {
      clearTimeout(arm)
      observer?.disconnect()
    }
  }, [scrollRef, start, onVisible])

  return (
    <div ref={sentinel} className="space-y-4">
      {showSkeleton ? (
        <>
          <div className="flex justify-end">
            <Skeleton className="h-9 w-56 rounded-2xl" />
          </div>
          <SkeletonText lines={3} />
        </>
      ) : null}
    </div>
  )
}

export function RunView({ id }: { id: string }) {
  const { state, error, loadOlder, loadingOlder, apply } = useRun(id)
  const list = useRuns()
  const scrollRef = useRef<HTMLDivElement>(null)
  const followBottom = useRef(true)
  const ready = Boolean(state)
  const [hiddenSession, setHiddenSession] = useState<number>()
  const modal = usePresence(
    browserShown(state, hiddenSession) ? state?.browser : undefined,
    BROWSER_EXIT_MS,
  )
  const browsing = Boolean(modal.shown)
  const wasOpen = useRef(false)
  const restoreHeight = useRef<number | undefined>(undefined)
  const [finding, setFinding] = useState(false)
  const arrivedLive = useArrivedLive(state)
  const edit = useQueuedEdit(id, state?.queued ?? NO_MESSAGES)

  useEffect(() => {
    const open = Boolean(state?.browser?.open)
    if (wasOpen.current && !open && state?.browser?.error)
      reportError(new Error(state.browser.error))
    wasOpen.current = open
  }, [state?.browser?.open, state?.browser?.error])

  const attention = allRuns(list).find((r) => r.id === id)?.attention
  const markSeen = useCallback(() => {
    if (attention && !document.hidden) void api.markRunSeen(id).catch(reportError)
  }, [id, attention])

  useEffect(markSeen, [markSeen])
  useWindowEvent('focus', markSeen)
  useWindowEvent(OPEN_FIND, () => setFinding(true))
  useWindowEvent('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.code !== 'KeyF') return

    const open = document.querySelector<HTMLInputElement>(`input[aria-label="${FIND_LABEL}"]`)
    if (open) {
      e.preventDefault()
      open.focus()
      open.select()
      return
    }

    if (layerOpen() || inCodeEditor(e.target)) return

    e.preventDefault()
    setFinding(true)
  })

  const older = useCallback(
    (until?: number) => {
      restoreHeight.current = scrollRef.current?.parentElement?.scrollHeight
      return loadOlder(until)
    },
    [loadOlder],
  )

  useLayoutEffect(() => {
    const scroller = scrollRef.current?.parentElement
    if (restoreHeight.current === undefined || !scroller) return
    scroller.scrollTop += scroller.scrollHeight - restoreHeight.current
    restoreHeight.current = undefined
  }, [state?.start])

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
  }, [ready, browsing])

  if (error)
    return (
      <Page title="Thread not found" subtitle={<span className="text-danger">{error}</span>}>
        {null}
      </Page>
    )

  if (!state) {
    return (
      <Page
        title={<Skeleton className="h-4 w-80" />}
        actions={<ActionsSkeleton widths={RUN_ACTION_WIDTHS} />}
        footer={<ComposerSkeleton />}
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
  const busy = WORKING.has(summary.status)
  const docked = dockedQuestion(state)
  const status = RUN_STATUS[summary.status]
  const turns = toTurns(state)
  const lastBlock = turns.at(-1)?.blocks.at(-1)
  const showThinking =
    summary.status === 'running' &&
    !(lastBlock?.kind === 'tools' && lastBlock.tools.some((t) => t.status === 'running')) &&
    !(lastBlock?.kind === 'item' && lastBlock.item.kind === 'text') &&
    !state.compactions.some((c) => c.status === 'running')

  const subtitle = (
    <>
      {summary.status === 'running' || summary.status === 'queued' ? (
        <Shimmer tone="brand" className="font-medium">
          {status.text}
        </Shimmer>
      ) : (
        <span
          className={cn('inline-flex items-center gap-1.5 font-medium', TONE_TEXT[status.tone])}
        >
          <StatusIcon status={summary.status} className="size-3" detailed />
          {status.text}
        </span>
      )}
      {summary.caseKey && state.caseUrl && !browsing ? (
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
      {state.instances.length > 0 && !browsing ? (
        <>
          <Dot />
          <InstanceChips instances={state.instances} />
        </>
      ) : null}
    </>
  )

  const listed = allRuns(list).find((r) => r.id === id)
  const settled = list?.settled.some((r) => r.id === id) ?? Boolean(summary.settled)
  const browser = state.browser?.open ? state.browser : undefined
  const lastInstance = state.instances.at(-1)
  const actions = (
    <>
      {browser && !browsing ? (
        <ShowBrowserButton
          instance={browser.instance ?? ''}
          driving={isBrowserTool(state.tools.findLast((t) => t.status === 'running')?.name)}
          onShow={() => setHiddenSession(undefined)}
        />
      ) : null}
      {lastInstance && !browser ? <OpenBrowserButton runId={id} instance={lastInstance} /> : null}
      <CostPill
        runId={id}
        provider={summary.provider}
        cost={summary.cost ?? (busy ? NOTHING_SPENT : undefined)}
        context={state.context}
        counting={summary.status === 'running'}
      />
      <RunMenu run={listed ?? summary} settled={settled} />
    </>
  )

  const stop = () => {
    for (const event of stopEvents(state)) apply(event)
    patchLocally(id, { status: 'cancelled' })
    void api.cancel(id).catch(reportError)
  }

  const page = (
    <ApplyContext.Provider value={apply}>
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
        compact={browsing}
        footer={
          <Footer
            runId={id}
            provider={summary.provider}
            idleSince={summary.updatedAt}
            run={listed ?? summary}
            settled={settled}
            busy={busy}
            status={summary.status}
            access={state.access}
            context={state.context}
            compact={browsing}
            question={docked}
            tool={state.tools.find((t) => t.id === docked?.toolId)}
            queued={state.queued}
            queueHeld={state.queueHeld}
            edit={edit}
            onStop={stop}
            onSend={() => {
              followBottom.current = true
            }}
          />
        }
      >
        {finding ? (
          <div className="pointer-events-none sticky top-0 z-30 h-0">
            <div className="pointer-events-auto">
              <FindBar
                runId={id}
                contentRef={scrollRef}
                start={state.start}
                version={`${state.start}:${state.items.length}`}
                onLoadUntil={older}
                onClose={() => setFinding(false)}
              />
            </div>
          </div>
        ) : null}
        {browsing ? null : (
          <ThreadRail
            contentRef={scrollRef}
            version={`${state.start}:${state.items.length}:${state.chat.length}:${state.tools.length}`}
            outline={state.outline}
            onLoadUntil={older}
            onJump={() => {
              followBottom.current = false
            }}
          />
        )}
        <div
          ref={scrollRef}
          className={cn(
            'mx-auto max-w-[860px] space-y-5 pt-6 pb-8',
            browsing ? 'px-4' : 'px-6 @max-[940px]:pr-11',
          )}
        >
          {state.continuedFrom && state.start === 0 ? (
            <ThreadLink label="Continued from" link={state.continuedFrom} />
          ) : null}
          {state.start > 0 ? (
            <OlderTurns
              scrollRef={scrollRef}
              start={state.start}
              loading={loadingOlder}
              onVisible={older}
            />
          ) : null}
          {turns.map((turn, i) => {
            const isLast = i === turns.length - 1
            const active = isLast && busy
            const { work, result } = active
              ? { work: [], result: turn.blocks }
              : splitTurn(turn.blocks)
            const text = blocksText(result, state)
            const toolIds = new Set(
              turn.blocks.flatMap((b) => (b.kind === 'tools' ? b.tools.map((x) => x.id) : [])),
            )

            const edits = state.edits.filter((e) => toolIds.has(e.toolId))
            const turnId = turn.user?.id

            return (
              <div key={turnId ?? `t${i}`} className="space-y-4">
                {turn.user ? (
                  <div
                    className={cn(arrivedLive(turn, turn.user.id) && 'animate-fade-up')}
                    data-mark="user"
                    data-start={turn.start}
                    data-label={turn.user.text.slice(0, MARK_LABEL_CHARS)}
                  >
                    <MemoUserMessage runId={id} message={turn.user} canRetry={!busy} />
                  </div>
                ) : null}
                {turn.blocks.length ? (
                  <div
                    data-mark="agent"
                    data-start={turn.start}
                    data-label={(text || 'Working').slice(0, MARK_LABEL_CHARS)}
                    className="space-y-4"
                  >
                    {work.length ? (
                      <Worked ms={turnSpan(turn, state)} summary={workSummary(work, state)}>
                        {work.map((b) => (
                          <ThreadBlock key={b.key} block={b} state={state} />
                        ))}
                      </Worked>
                    ) : null}
                    {result.map((b) => (
                      <div
                        key={b.key}
                        className={cn(arrivedLive(turn, b.key) && 'animate-fade-up')}
                      >
                        <ThreadBlock block={b} state={state} />
                      </div>
                    ))}
                    {active ? null : <FilesChanged runId={id} edits={edits} />}
                  </div>
                ) : null}
                {!active && turnId && text ? (
                  <AssistantActions
                    runId={id}
                    turnId={turnId}
                    text={text}
                    ts={turnTime(turn, state)}
                    canRetry={!busy}
                  />
                ) : null}
              </div>
            )
          })}
          {showThinking ? (
            <div className="text-[12.5px]">
              <Shimmer>Thinking</Shimmer>
            </div>
          ) : null}
          <QueuedMessages
            runId={id}
            queued={state.queued}
            held={state.queueHeld}
            status={summary.status}
            editingId={edit.editing?.id}
            canEdit={!docked}
            onEdit={edit.startEdit}
            onCancelEdit={edit.endEdit}
          />
          {state.continuedIn ? <ThreadLink label="Continued in" link={state.continuedIn} /> : null}
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
    </ApplyContext.Provider>
  )

  if (!modal.shown) return page

  const shownBrowser = modal.shown

  return createPortal(
    <div className={cn('fixed inset-0 z-[90]', modal.leaving && 'pointer-events-none')}>
      <BrowserBackdrop leaving={modal.leaving} />
      <BrowserPane
        runId={id}
        browser={shownBrowser}
        tools={state.tools}
        question={browserQuestion(state)}
        access={state.access}
        leaving={modal.leaving}
        onHide={() => setHiddenSession(shownBrowser.session)}
      />
      <div
        className={cn(CARD_CLASS, modal.leaving ? 'animate-side-out' : 'animate-side-in')}
        style={CHAT_CARD_STYLE}
      >
        {page}
      </div>
    </div>,
    document.body,
  )
}
