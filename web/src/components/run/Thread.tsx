import { Fragment, memo, type RefObject, useEffect, useRef } from 'react'
import type { Question, RunState, RunSummary } from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { Shimmer, Skeleton, SkeletonText } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { BranchedIntoNotes, InheritedToggle, LineageNote } from './Branches'
import { FilesChanged } from './FilesChanged'
import { AssistantActions, UserMessage } from './Messages'
import { QueuedMessages } from './QueuedMessages'
import type { QueuedEdit } from './RunFooter'
import { ThreadBlock } from './ThreadBlock'
import {
  blocksText,
  inheritedTurn,
  isThinking,
  nextTurnId,
  splitTurn,
  type Turn,
  turnSpan,
  turnTime,
  workSummary,
} from './threadTurns'
import { Worked } from './Worked'

const MARK_LABEL_CHARS = 160
const OLDER_MARGIN_PX = 600
const OLDER_ARM_MS = 500

const MemoUserMessage = memo(UserMessage)

function OlderTurns({
  scrollRef,
  start,
  loading,
  onVisible,
}: {
  scrollRef: RefObject<HTMLDivElement | null>
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

export function Thread({
  runId,
  state,
  turns,
  inheritedCount,
  busy,
  browsing,
  docked,
  edit,
  branches,
  showInherited,
  loadingOlder,
  scrollRef,
  arrivedLive,
  onShowInherited,
  onLoadOlder,
}: {
  runId: string
  state: RunState
  turns: Turn[]
  inheritedCount: number
  busy: boolean
  browsing: boolean
  docked?: Question
  edit: QueuedEdit
  branches: RunSummary[]
  showInherited: boolean
  loadingOlder: boolean
  scrollRef: RefObject<HTMLDivElement | null>
  arrivedLive: (turn: Turn, key: string) => boolean
  onShowInherited: (show: boolean) => void
  onLoadOlder: () => Promise<void>
}) {
  const { summary } = state

  return (
    <div
      ref={scrollRef}
      className={cn(
        'mx-auto max-w-[860px] space-y-5 pt-6 pb-8',
        browsing ? 'px-4' : 'px-6 @max-[940px]:pr-11',
      )}
    >
      {state.start === 0 ? (
        <BranchedIntoNotes branches={branches.filter((b) => !b.originTurnId)} />
      ) : null}
      {inheritedCount && !showInherited ? (
        <>
          <InheritedToggle
            turns={inheritedCount}
            open={false}
            onToggle={() => onShowInherited(true)}
          />
          <LineageNote label="Branched from" thread={state.parent} />
        </>
      ) : null}
      {state.start > 0 && (showInherited || state.start >= (state.inheritedItems ?? 0)) ? (
        <OlderTurns
          scrollRef={scrollRef}
          start={state.start}
          loading={loadingOlder}
          onVisible={onLoadOlder}
        />
      ) : null}
      {turns.map((turn, i) => {
        const inherited = inheritedTurn(turn, state)
        if (inherited && !showInherited) return null

        const isLast = i === turns.length - 1
        const active = isLast && busy
        const lastInherited = inherited && (isLast || !inheritedTurn(turns[i + 1], state))
        const { work, result } = active ? { work: [], result: turn.blocks } : splitTurn(turn.blocks)
        const text = blocksText(result, state)
        const toolIds = new Set(
          turn.blocks.flatMap((b) => (b.kind === 'tools' ? b.tools.map((x) => x.id) : [])),
        )

        const edits = state.edits.filter((e) => toolIds.has(e.toolId))
        const turnId = turn.user?.id

        return (
          <Fragment key={turnId ?? `t${i}`}>
            <div className={cn('space-y-4', inherited && 'opacity-70')}>
              {turn.user ? (
                <div
                  className={cn(arrivedLive(turn, turn.user.id) && 'animate-fade-up')}
                  data-mark="user"
                  data-start={turn.start}
                  data-label={turn.user.text.slice(0, MARK_LABEL_CHARS)}
                >
                  <MemoUserMessage
                    runId={runId}
                    message={turn.user}
                    canRetry={!busy && !inherited}
                    canBranch={!active && !turn.user.steer}
                  />
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
                        <ThreadBlock key={b.key} block={b} state={state} inherited={inherited} />
                      ))}
                    </Worked>
                  ) : null}
                  {result.map((b) => (
                    <div key={b.key} className={cn(arrivedLive(turn, b.key) && 'animate-fade-up')}>
                      <ThreadBlock block={b} state={state} inherited={inherited} />
                    </div>
                  ))}
                  {active ? null : <FilesChanged runId={runId} edits={edits} />}
                </div>
              ) : null}
              {!active && turnId && text ? (
                <AssistantActions
                  runId={runId}
                  turnId={turnId}
                  text={text}
                  ts={turnTime(turn, state)}
                  canRetry={!busy && !inherited}
                  nextTurnId={nextTurnId(turns, i)}
                />
              ) : null}
            </div>
            {lastInherited ? (
              <div className="space-y-4">
                <InheritedToggle
                  turns={inheritedCount}
                  open
                  onToggle={() => onShowInherited(false)}
                />
                <LineageNote label="Branched from" thread={state.parent} />
              </div>
            ) : null}
            {turnId ? (
              <BranchedIntoNotes branches={branches.filter((b) => b.originTurnId === turnId)} />
            ) : null}
          </Fragment>
        )
      })}
      {isThinking(state, turns) ? (
        <div className="text-[12.5px]">
          <Shimmer>Thinking</Shimmer>
        </div>
      ) : null}
      <QueuedMessages
        runId={runId}
        queued={state.queued}
        held={state.queueHeld}
        status={summary.status}
        editingId={edit.editing?.id}
        canEdit={!docked}
        onEdit={edit.startEdit}
        onCancelEdit={edit.endEdit}
      />
      {state.error && summary.status === 'error' ? (
        <div className="border-danger/40 bg-danger-soft/50 text-danger rounded-2xl border px-4 py-3 text-[13px]">
          {state.error}
        </div>
      ) : null}
    </div>
  )
}
