import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ChatMessage } from '@shared/types.ts'
import { EditableTitle } from '@/components/common/EditableTitle'
import { reportError } from '@/components/common/Toasts'
import { Page } from '@/components/common/ui'
import { OPEN_FIND } from '@/components/layout/CommandPalette'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { inCodeEditor } from '@/lib/dom'
import { usePresence, useWindowEvent } from '@/lib/hooks'
import { layerOpen } from '@/lib/layers'
import { ApplyContext, stopEvents } from '@/lib/optimistic'
import { allRuns, patchLocally, useRuns, WORKING } from '@/lib/runs'
import { useRun } from '@/lib/useRun'
import { useBranches } from './Branches'
import { BrowserBackdrop, BrowserPane, CARD_CLASS, CHAT_CARD_STYLE } from './BrowserPane'
import { FIND_LABEL, FindBar } from './FindBar'
import { RunFooter, useQueuedEdit } from './RunFooter'
import { RunActions, RunLoading, RunSubtitle } from './RunHeader'
import { Thread } from './Thread'
import { ThreadRail } from './ThreadRail'
import {
  browserQuestion,
  browserShown,
  dockedQuestion,
  freshBranchTurns,
  inheritedTurnCount,
  toTurns,
  useArrivedLive,
} from './threadTurns'
import { useThreadScroll } from './useThreadScroll'

const BROWSER_EXIT_MS = 200
const NO_MESSAGES: ChatMessage[] = []

export function RunView({ id }: { id: string }) {
  const { state, error, loadOlder, loadingOlder, apply } = useRun(id)
  const list = useRuns()
  const scrollRef = useRef<HTMLDivElement>(null)
  const ready = Boolean(state)
  const [hiddenSession, setHiddenSession] = useState<number>()
  const modal = usePresence(
    browserShown(state, hiddenSession) ? state?.browser : undefined,
    BROWSER_EXIT_MS,
  )
  const browsing = Boolean(modal.shown)
  const wasOpen = useRef(false)
  const [finding, setFinding] = useState(false)
  const [showInherited, setShowInherited] = useState(false)
  const branches = useBranches(id)
  const arrivedLive = useArrivedLive(state)
  const edit = useQueuedEdit(id, state?.queued ?? NO_MESSAGES)
  const chat = state?.chat ?? NO_MESSAGES
  const userTexts = useMemo(
    () => chat.filter((m) => m.role === 'user' && m.text).map((m) => m.text),
    [chat],
  )

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

  useEffect(() => {
    setShowInherited(false)
  }, [id])

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

  const { followBottom, older } = useThreadScroll(
    scrollRef,
    loadOlder,
    state?.start,
    ready,
    browsing,
  )

  if (error)
    return (
      <Page title="Thread not found" subtitle={<span className="text-danger">{error}</span>}>
        {null}
      </Page>
    )

  if (!state) return <RunLoading />

  const { summary } = state
  const busy = WORKING.has(summary.status)
  const docked = dockedQuestion(state)
  const turns = toTurns(state)
  const inheritedCount = inheritedTurnCount(state, turns)
  const listed = allRuns(list).find((r) => r.id === id)
  const settled = list?.settled.some((r) => r.id === id) ?? Boolean(summary.settled)

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
        subtitle={<RunSubtitle state={state} browsing={browsing} />}
        actions={
          <RunActions
            runId={id}
            state={state}
            run={listed ?? summary}
            settled={settled}
            busy={busy}
            browsing={browsing}
            onShowBrowser={() => setHiddenSession(undefined)}
          />
        }
        compact={browsing}
        footer={
          <RunFooter
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
            freshBranchTurns={freshBranchTurns(state, inheritedCount)}
            edit={edit}
            history={userTexts}
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
        <Thread
          runId={id}
          state={state}
          turns={turns}
          inheritedCount={inheritedCount}
          busy={busy}
          browsing={browsing}
          docked={docked}
          edit={edit}
          branches={branches}
          showInherited={showInherited}
          loadingOlder={loadingOlder}
          scrollRef={scrollRef}
          arrivedLive={arrivedLive}
          onShowInherited={setShowInherited}
          onLoadOlder={older}
        />
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
