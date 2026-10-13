import { ArrowSquareOut as ArrowTopRightOnSquareIcon } from '@phosphor-icons/react'
import { Composer } from '@/components/Composer'
import { EditableTitle } from '@/components/EditableTitle'
import { WriteSwitch } from '@/components/WriteSwitch'
import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ChatMessage, FollowUp, RunState, ThreadItem, ToolActivity } from '@shared/types.ts'
import { StatusIcon } from '@/components/Sidebar'
import { Dot, Markdown, Page, Skeleton, SkeletonText, Spinner, type Tone } from '@/components/ui'
import { api } from '@/lib/api'
import { reportError } from '@/components/Toasts'
import { cn } from '@/lib/cn'
import { useSettings } from '@/lib/settings'
import { useRun } from '@/lib/useRun'
import { useSkeleton } from '@/components/skeletons'
import { useRuns } from '@/lib/runs'
import { ChangeCard } from './ChangeCard'
import { CostPill } from './CostPill'
import { FilesChanged } from './FilesChanged'
import { FindBar } from './FindBar'
import { InstanceChip } from './InstanceChip'
import { RunMenu } from '@/components/RunMenu'
import { layerOpen } from '@/lib/layers'
import { OPEN_FIND } from '@/components/CommandPalette'
import { ThreadRail } from './ThreadRail'
import { AssistantActions, QueuedMessage, UserMessage } from './Messages'
import { Answer, LoginCard, QuestionCard } from './Panels'
import { ToolGroup } from './ToolGroup'

const FOLLOW_BOTTOM_PX = 80
const USER_SCROLL_MS = 600
const USER_SCROLL_EVENTS = ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const
const MARK_LABEL_CHARS = 160
const OLDER_MARGIN_PX = 600
const OLDER_ARM_MS = 500

const MemoChangeCard = memo(ChangeCard)
const MemoAnswer = memo(Answer)
const MemoUserMessage = memo(UserMessage)

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

function turnText(turn: Turn, state: RunState): string {
  const parts: string[] = []
  for (const b of turn.blocks) {
    if (b.kind !== 'item') continue
    if (b.item.kind === 'text') {
      const t = chatById(state).get(b.item.id)?.text.trim()
      if (t) parts.push(t)
    } else if (b.item.kind === 'outcome' && b.item.id === state.outcomeId && state.outcome) {
      for (const i of state.outcome.issues) parts.push(`${i.title}: ${i.summary}`)
      if (state.outcome.reply) parts.push(state.outcome.reply)
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

function ThreadBlock({ block, state }: { block: Block; state: RunState }) {
  if (block.kind === 'tools') return <ToolGroup runId={state.summary.id} tools={block.tools} />

  const { item } = block
  const id = state.summary.id
  switch (item.kind) {
    case 'text': {
      const msg = chatById(state).get(item.id)
      if (!msg?.text.trim()) return null
      return (
        <div className="text-fg">
          <Markdown text={msg.text} links={msg.links} />
        </div>
      )
    }
    case 'change': {
      const change = indexed(changeIndex, state.changes).get(item.id)
      return change ? <MemoChangeCard change={change} /> : null
    }
    case 'question': {
      const q = state.questions.find((x) => x.id === item.id)
      const live = ['running', 'waiting'].includes(state.summary.status)
      return q ? <QuestionCard runId={id} question={q} live={live} /> : null
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

  const { settings } = useSettings()
  const other: FollowUp = settings.followUp === 'steer' ? 'queue' : 'steer'
  const describe = (mode: FollowUp) =>
    mode === 'steer' ? 'Steer: picked up at the next step' : 'Queue: sent after this turn'

  const send = async (text: string, files: File[] = [], alternate = false) => {
    setError(undefined)
    onSend()
    try {
      const uploaded = files.length ? await api.upload(files) : []
      await api.message(runId, text, uploaded, alternate && busy ? other : settings.followUp)
    } catch (e) {
      setError((e as Error).message)
      throw e
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
              ? `${describe(settings.followUp)}. Ctrl+Enter to ${other} instead`
              : 'Ask a follow-up or give direction'
          }
          busyHint={(alternate) => describe(alternate ? other : settings.followUp)}
          onSend={(text, files, alternate) => send(text, files, alternate)}
          draftKey={`run-${runId}`}
          onStop={() => void api.cancel(runId).catch(reportError)}
          extras={<WriteSwitch value={write} onChange={(v) => api.setWriteAccess(runId, v)} />}
        />
      </div>
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
  const { state, error, loadOlder, loadingOlder } = useRun(id)
  const list = useRuns()
  const scrollRef = useRef<HTMLDivElement>(null)
  const followBottom = useRef(true)
  const ready = Boolean(state)
  const restoreHeight = useRef<number | undefined>(undefined)
  const [finding, setFinding] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.code !== 'KeyF') return
      const open = document.querySelector<HTMLInputElement>('input[aria-label="Find in thread"]')
      if (open) {
        e.preventDefault()
        open.focus()
        open.select()
        return
      }
      if (layerOpen() || (e.target as HTMLElement | null)?.closest?.('.monaco-editor')) return
      e.preventDefault()
      setFinding(true)
    }
    const onFind = () => setFinding(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener(OPEN_FIND, onFind)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(OPEN_FIND, onFind)
    }
  }, [])

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
      {summary.instance ? (
        <>
          <Dot />
          <InstanceChip instance={summary.instance} />
        </>
      ) : null}
    </>
  )

  const listed = [...(list?.active ?? []), ...(list?.snoozed ?? []), ...(list?.settled ?? [])].find(
    (r) => r.id === id,
  )
  const settled = list?.settled.some((r) => r.id === id) ?? Boolean(summary.settled)
  const actions = (
    <>
      {busy && !summary.cost ? null : <CostPill runId={id} cost={summary.cost} />}
      <RunMenu run={listed ?? summary} settled={settled} />
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
      {finding ? (
        <div className="pointer-events-none sticky top-0 z-30 h-0">
          <div className="pointer-events-auto">
            <FindBar
              runId={id}
              contentRef={scrollRef}
              start={state.start}
              version={state.start * 100_000 + state.items.length}
              onLoadUntil={older}
              onClose={() => setFinding(false)}
            />
          </div>
        </div>
      ) : null}
      <ThreadRail
        contentRef={scrollRef}
        version={`${state.start}:${state.items.length}:${state.chat.length}:${state.tools.length}`}
        outline={state.outline}
        onLoadUntil={older}
        onJump={() => {
          followBottom.current = false
        }}
      />
      <div
        ref={scrollRef}
        className="mx-auto max-w-[860px] space-y-5 px-6 pt-6 pb-8 @max-[940px]:pr-11"
      >
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
          const text = turnText(turn, state)
          const toolIds = new Set(
            turn.blocks.flatMap((b) => (b.kind === 'tools' ? b.tools.map((x) => x.id) : [])),
          )
          const edits = state.edits.filter((e) => toolIds.has(e.toolId))
          const turnId = turn.user?.id

          return (
            <div key={turnId ?? `t${i}`} className="space-y-4">
              {turn.user ? (
                <div
                  className="animate-fade-up"
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
                  {turn.blocks.map((b) => (
                    <div key={b.key} className="animate-fade-up">
                      <ThreadBlock block={b} state={state} />
                    </div>
                  ))}
                  <FilesChanged runId={id} edits={edits} />
                </div>
              ) : null}
              {!active && turnId && text ? (
                <AssistantActions
                  runId={id}
                  turnId={turnId}
                  replyFrom={
                    turn.blocks.findLast(
                      (b): b is Extract<Block, { kind: 'item' }> =>
                        b.kind === 'item' && b.item.kind === 'text',
                    )?.item.id
                  }
                  text={text}
                  ts={turnTime(turn, state)}
                  canRetry={!busy}
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
