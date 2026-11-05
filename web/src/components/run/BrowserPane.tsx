import {
  Browser as BrowserIcon,
  ArrowsIn as HideIcon,
  Cursor as CursorIcon,
  Prohibit as ProhibitIcon,
  ShieldWarning as ShieldWarningIcon,
  X as CloseIcon,
} from '@phosphor-icons/react'
import { useState } from 'react'
import type {
  Access,
  BrowserDialog,
  BrowserPointer,
  BrowserState,
  BrowserTab,
  ApprovalQuestion,
  ToolActivity,
} from '@shared/types.ts'
import { LiveScreen, type FrameSize } from '@/components/screen/LiveScreen'
import { reportError } from '@/components/common/Toasts'
import { Button, Shimmer } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useLayer } from '@/lib/layers'
import { useAnswer } from './QuestionDock'

const BROWSER_TOOL_PREFIX = 'browser_'
const CARD_GAP_PX = 16
const CHAT_CARD_WIDTH_PX = 440
const CARD_SHADOW = 'shadow-[0_20px_60px_rgba(38,50,56,0.3)]'

export const CARD_CLASS = `fixed overflow-hidden rounded-2xl bg-white ${CARD_SHADOW}`
export const CHAT_CARD_STYLE = {
  top: CARD_GAP_PX,
  bottom: CARD_GAP_PX,
  right: CARD_GAP_PX,
  width: CHAT_CARD_WIDTH_PX,
}
const BROWSER_CARD_STYLE = {
  top: CARD_GAP_PX,
  bottom: CARD_GAP_PX,
  left: CARD_GAP_PX,
  right: CHAT_CARD_WIDTH_PX + CARD_GAP_PX * 2,
}

export function isBrowserTool(name: string | undefined): boolean {
  return Boolean(name?.startsWith(BROWSER_TOOL_PREFIX))
}

function lastBrowserTool(tools: ToolActivity[]): ToolActivity | undefined {
  for (let i = tools.length - 1; i >= 0; i--) if (isBrowserTool(tools[i].name)) return tools[i]
  return undefined
}

function Pointer({ pointer, size }: { pointer: BrowserPointer; size: FrameSize }) {
  return (
    <div
      className="animate-fade-in pointer-events-none absolute z-10 transition-[left,top] duration-(--duration-travel) ease-out"
      style={{
        left: `${(pointer.x / size.width) * 100}%`,
        top: `${(pointer.y / size.height) * 100}%`,
      }}
    >
      {pointer.press ? (
        <span
          key={pointer.step}
          className="animate-tap bg-brand/40 absolute top-0 left-0 size-12 rounded-full"
        />
      ) : null}
      <span
        key={pointer.press ? pointer.step : 'still'}
        className={cn('block origin-top-left', pointer.press && 'animate-cursor-press')}
      >
        <CursorIcon
          weight="fill"
          className="text-brand-strong size-6 -translate-x-[3px] -translate-y-[2px] drop-shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
        />
      </span>
    </div>
  )
}

function Caption({ tool, access }: { tool: ToolActivity | undefined; access: Access }) {
  if (!tool) return null

  const blocked = tool.status === 'error' && tool.verdict?.effect === 'write' && access === 'read'
  if (tool.status !== 'running' && !blocked) return null

  const change = tool.verdict?.effect === 'write'

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-4 z-10 flex justify-center px-6">
      <div
        key={`${tool.id}-${tool.status}`}
        title={tool.verdict?.reason}
        className={cn(
          'animate-fade-up flex max-w-full items-center gap-2 rounded-full px-3.5 py-1.5 text-[12.5px] text-white shadow-[0_6px_20px_rgba(38,50,56,0.3)]',
          blocked ? 'bg-danger' : 'bg-[#263238]/85',
        )}
      >
        {blocked ? <ProhibitIcon className="size-3.5 shrink-0" /> : null}
        {blocked ? (
          <span className="truncate">Blocked: {tool.label}</span>
        ) : (
          <Shimmer tone="light" className="truncate">
            {tool.label}
          </Shimmer>
        )}
        {tool.verdict ? (
          <span
            className={cn(
              'shrink-0 rounded-full px-1.5 text-[11px] font-medium',
              change ? 'bg-warn text-white' : 'bg-white/15',
            )}
          >
            {blocked ? 'needs Allow changes' : change ? 'change' : 'read only'}
          </span>
        ) : null}
      </div>
    </div>
  )
}

function tabName(tab: BrowserTab): string {
  if (tab.title) return tab.title
  if (!URL.canParse(tab.url)) return tab.url
  return new URL(tab.url).pathname
}

function Tabs({ runId, tabs }: { runId: string; tabs: BrowserTab[] }) {
  if (tabs.length < 2) return null

  const act = (index: number, close: boolean) =>
    void api.browserTab(runId, index, close).catch(reportError)

  return (
    <div
      role="tablist"
      aria-label="Browser tabs"
      className="border-line animate-fade-in flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-1.5"
    >
      {tabs.map((tab) => (
        <div
          key={tab.index}
          className={cn(
            'group flex h-7 max-w-56 min-w-0 shrink-0 items-center rounded-full text-[12px] transition-colors',
            tab.active ? 'bg-brand-soft text-fg' : 'text-muted hover:bg-raised',
          )}
        >
          <button
            type="button"
            role="tab"
            aria-selected={tab.active}
            title={tab.url}
            onClick={() => act(tab.index, false)}
            className="min-w-0 truncate py-1 pr-1 pl-3"
          >
            {tabName(tab)}
          </button>
          <button
            type="button"
            aria-label={`Close ${tabName(tab)}`}
            title="Close this tab"
            onClick={() => act(tab.index, true)}
            className="text-faint hover:text-fg mr-1 flex size-5 shrink-0 items-center justify-center rounded-full hover:bg-white"
          >
            <CloseIcon className="size-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

const DIALOG_TITLES: Record<BrowserDialog['kind'], string> = {
  alert: 'The page says',
  confirm: 'The page asks',
  prompt: 'The page asks',
  beforeunload: 'Leave this page?',
}

function PageDialog({
  runId,
  dialog,
  instance,
}: {
  runId: string
  dialog: BrowserDialog
  instance: string
}) {
  const [text, setText] = useState(dialog.default)
  const [sending, setSending] = useState(false)
  const answer = (accept: boolean) => {
    setSending(true)
    api
      .answerBrowserDialog(runId, accept, text)
      .catch(reportError)
      .finally(() => setSending(false))
  }

  return (
    <div className="animate-fade-in absolute inset-0 z-20 flex justify-center bg-[#263238]/20 px-6 pt-6">
      <form
        role="alertdialog"
        aria-label={DIALOG_TITLES[dialog.kind]}
        onSubmit={(e) => {
          e.preventDefault()
          answer(true)
        }}
        className="animate-pop h-fit w-full max-w-[420px] rounded-xl bg-white p-4 shadow-[0_12px_40px_rgba(38,50,56,0.3)]"
      >
        <div className="text-fg text-[13.5px] font-semibold">
          {instance} &middot; {DIALOG_TITLES[dialog.kind]}
        </div>
        <div className="text-text mt-1.5 max-h-48 scrollbar-thin overflow-auto text-[13px] [overflow-wrap:anywhere] whitespace-pre-wrap">
          {dialog.message}
        </div>
        {dialog.kind === 'prompt' ? (
          <input
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="border-line focus:border-brand mt-3 h-8 w-full rounded-lg border px-2.5 text-[13px] outline-none"
          />
        ) : null}
        <div className="mt-3.5 flex justify-end gap-1.5">
          {dialog.kind === 'alert' ? null : (
            <Button variant="ghost" type="button" disabled={sending} onClick={() => answer(false)}>
              Cancel
            </Button>
          )}
          <Button variant="primary" type="submit" busy={sending} disabled={sending}>
            OK
          </Button>
        </div>
      </form>
    </div>
  )
}

function Approval({ runId, question }: { runId: string; question: ApprovalQuestion }) {
  const { sending, send } = useAnswer(runId, question.id)

  return (
    <div className="animate-fade-in absolute inset-0 z-20 flex items-center justify-center bg-[#263238]/35 p-6 backdrop-blur-[1px]">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Approve this change"
        className="animate-pop w-full max-w-[440px] rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.3)]"
      >
        <div className="flex items-start gap-3.5 px-5 pt-5">
          <span className="bg-warn-soft text-warn flex size-10 shrink-0 items-center justify-center rounded-full">
            <ShieldWarningIcon className="size-5" />
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-fg text-[15px] font-semibold">Approve this change?</div>
            <div className="text-text mt-0.5 text-[13px]">{question.question}</div>
          </div>
        </div>
        <pre className="bg-raised text-fg mx-5 mt-3.5 max-h-40 scrollbar-thin overflow-auto rounded-xl px-3 py-2 font-mono text-[11.5px] leading-[18px] break-words whitespace-pre-wrap">
          {question.detail}
        </pre>
        <div className="flex justify-end gap-1.5 px-5 py-4">
          <Button variant="ghost" disabled={sending} onClick={() => send(['Reject'])}>
            Reject
          </Button>
          <Button
            variant="primary"
            busy={sending}
            disabled={sending}
            onClick={() => send(['Approve'])}
          >
            Approve
          </Button>
        </div>
      </div>
    </div>
  )
}

export function BrowserBackdrop({ leaving }: { leaving: boolean }) {
  return (
    <div
      className={cn(
        'fixed inset-0 bg-[#263238]/30 backdrop-blur-[2px]',
        leaving ? 'animate-fade-out' : 'animate-fade-in',
      )}
    />
  )
}

export function BrowserPane({
  runId,
  browser,
  tools,
  question,
  access,
  leaving,
  onHide,
}: {
  runId: string
  browser: BrowserState
  tools: ToolActivity[]
  question: ApprovalQuestion | undefined
  access: Access
  leaving: boolean
  onHide: () => void
}) {
  const last = lastBrowserTool(tools)
  const instance = browser.instance ?? ''
  useLayer(onHide, !question)

  return (
    <div
      role="dialog"
      aria-label={`Browser on ${instance}`}
      className={cn(
        CARD_CLASS,
        'flex min-w-0 flex-col',
        leaving ? 'animate-card-sink' : 'animate-card-rise',
      )}
      style={BROWSER_CARD_STYLE}
    >
      <LiveScreen
        key={browser.session}
        streamUrl={api.browserScreenUrl(runId)}
        send={(events) => api.browserInput(runId, events)}
        address={instance}
        label={`Browser on ${instance}`}
        starting={`Opening ${instance}`}
        closeLabel="Close the browser"
        onClose={() => void api.closeBrowser(runId).catch(reportError)}
        focusOnStart={false}
        loading={browser.loading}
        onStageResize={(size) => void api.resizeBrowser(runId, size).catch(reportError)}
        strip={<Tabs runId={runId} tabs={browser.tabs ?? []} />}
        status={
          <button
            type="button"
            onClick={onHide}
            aria-label="Hide the browser"
            title="Hide the browser and keep it running (Esc)"
            className="text-faint hover:text-fg hover:bg-raised flex size-8 shrink-0 items-center justify-center rounded-full transition-colors"
          >
            <HideIcon className="size-4" />
          </button>
        }
        overlay={(size) => (
          <>
            {browser.pointer ? <Pointer pointer={browser.pointer} size={size} /> : null}
            <Caption tool={last} access={access} />
            {browser.dialog ? (
              <PageDialog
                key={`${browser.dialog.kind}:${browser.dialog.message}`}
                runId={runId}
                dialog={browser.dialog}
                instance={instance}
              />
            ) : null}
          </>
        )}
      />
      {question ? <Approval runId={runId} question={question} /> : null}
    </div>
  )
}

export const HEADER_PILL =
  'bg-raised text-text hover:bg-line-strong/45 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12px] font-medium whitespace-nowrap transition-colors disabled:opacity-60'

export function OpenBrowserButton({ runId, instance }: { runId: string; instance: string }) {
  const [opening, setOpening] = useState(false)

  const open = () => {
    setOpening(true)
    api
      .openBrowser(runId, instance)
      .catch(reportError)
      .finally(() => setOpening(false))
  }

  return (
    <button
      type="button"
      disabled={opening}
      onClick={open}
      title={`Open ${instance} beside the chat`}
      className={cn(HEADER_PILL, opening && 'busy-sweep')}
    >
      <BrowserIcon className="text-brand-strong size-3.5" />
      {opening ? 'Opening' : 'Browser'}
    </button>
  )
}

export function ShowBrowserButton({
  instance,
  driving,
  onShow,
}: {
  instance: string
  driving: boolean
  onShow: () => void
}) {
  return (
    <button
      type="button"
      onClick={onShow}
      title={
        driving ? `The agent is using ${instance}. Show it` : `Show the browser on ${instance}`
      }
      className={HEADER_PILL}
    >
      <span className={cn('bg-ok inline-flex size-2 rounded-full', driving && 'live-ring')} />
      Browser
    </button>
  )
}
