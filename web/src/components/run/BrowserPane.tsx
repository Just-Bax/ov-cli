import {
  Browser as BrowserIcon,
  ArrowsIn as HideIcon,
  Cursor as CursorIcon,
  Eye as EyeIcon,
  Prohibit as ProhibitIcon,
  ShieldWarning as ShieldWarningIcon,
} from '@phosphor-icons/react'
import { useState } from 'react'
import type { BrowserPointer, BrowserState, Question, ToolActivity } from '@shared/types.ts'
import { LiveScreen, type FrameSize } from '@/components/screen/LiveScreen'
import { reportError } from '@/components/common/Toasts'
import { Button, Spinner } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useLayer } from '@/lib/layers'
import { useAnswer } from './Panels'

const BROWSER_TOOL_PREFIX = 'browser_'
const CARD_GAP_PX = 16
const CHAT_CARD_WIDTH_PX = 440
const CARD_SHADOW = 'shadow-[0_20px_60px_rgba(38,50,56,0.3)]'

export const CARD_CLASS = `animate-pop fixed overflow-hidden rounded-2xl bg-white ${CARD_SHADOW}`
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
      className="pointer-events-none absolute z-10 transition-[left,top] duration-300 ease-out"
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
      <CursorIcon
        weight="fill"
        className="text-brand-strong size-6 -translate-x-[3px] -translate-y-[2px] drop-shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
      />
    </div>
  )
}

function Caption({ tool, write }: { tool: ToolActivity | undefined; write: boolean }) {
  if (!tool) return null

  const blocked = tool.status === 'error' && tool.verdict?.effect === 'write' && !write
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
        {blocked ? (
          <ProhibitIcon className="size-3.5 shrink-0" />
        ) : (
          <Spinner className="size-3 shrink-0" />
        )}
        <span className="truncate">{blocked ? `Blocked: ${tool.label}` : tool.label}</span>
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

function Approval({ runId, question }: { runId: string; question: Question }) {
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
          <Button variant="ghost" disabled={sending} onClick={() => send('Reject')}>
            Reject
          </Button>
          <Button variant="primary" disabled={sending} onClick={() => send('Approve')}>
            {sending ? <Spinner className="size-3.5" /> : null} Approve
          </Button>
        </div>
      </div>
    </div>
  )
}

export function BrowserBackdrop() {
  return <div className="animate-fade-in fixed inset-0 bg-[#263238]/30 backdrop-blur-[2px]" />
}

export function BrowserPane({
  runId,
  browser,
  tools,
  question,
  write,
  onHide,
}: {
  runId: string
  browser: BrowserState
  tools: ToolActivity[]
  question: Question | undefined
  write: boolean
  onHide: () => void
}) {
  const last = lastBrowserTool(tools)
  const driving = last?.status === 'running'
  const instance = browser.instance ?? ''
  useLayer(onHide, !question)

  return (
    <div
      role="dialog"
      aria-label={`Browser on ${instance}`}
      className={cn(CARD_CLASS, 'flex min-w-0 flex-col')}
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
        onStageResize={(size) => void api.resizeBrowser(runId, size).catch(reportError)}
        status={
          <>
            <span
              className={cn(
                'hidden h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12px] font-medium sm:inline-flex',
                write ? 'bg-warn-soft text-warn' : 'bg-raised text-muted',
              )}
              title={
                write
                  ? 'Each change in the browser waits for your approval'
                  : 'Changes in the browser are blocked'
              }
            >
              {driving ? <Spinner className="size-3" /> : <EyeIcon className="size-3.5" />}
              {write ? 'Changes need approval' : 'Read only'}
            </span>
            <button
              type="button"
              onClick={onHide}
              title="Hide the browser and keep it running (Esc)"
              className="text-muted hover:bg-raised hover:text-fg flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12px] font-medium transition-colors"
            >
              <HideIcon className="size-3.5" />
              Hide
            </button>
          </>
        }
        overlay={(size) => (
          <>
            {browser.pointer ? <Pointer pointer={browser.pointer} size={size} /> : null}
            <Caption tool={last} write={write} />
          </>
        )}
      />
      {question ? <Approval runId={runId} question={question} /> : null}
    </div>
  )
}

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
    <Button
      variant="secondary"
      disabled={opening}
      onClick={open}
      title={`Open ${instance} beside the chat`}
    >
      {opening ? <Spinner className="size-3.5" /> : <BrowserIcon className="size-4" />}
      Open browser
    </Button>
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
    <Button variant="secondary" onClick={onShow} title={`Show the browser on ${instance}`}>
      {driving ? <Spinner className="size-3.5" /> : <BrowserIcon className="size-4" />}
      Show browser
    </Button>
  )
}
