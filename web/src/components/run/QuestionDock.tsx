import {
  CaretDown as CaretDownIcon,
  CaretLeft as CaretLeftIcon,
  CaretRight as CaretRightIcon,
  Check as CheckIcon,
  Minus as MinusIcon,
  ShieldWarning as ShieldWarningIcon,
  X as XIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useRef, useState } from 'react'
import type {
  ApprovalQuestion,
  AskQuestion,
  Question,
  QuestionItem,
  ToolActivity,
} from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button, Chip, CopyButton } from '@/components/common/ui'
import { Composer } from '@/components/composer/Composer'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { isEditableTarget } from '@/lib/dom'
import { useWindowEvent } from '@/lib/hooks'

const APPROVE = 'Approve'
const REJECT = 'Reject'
const MAX_KEYED_OPTIONS = 9
const ANSWER_JOINER = ', '
const DOCK_CLASS =
  'border-line-strong relative -mb-6 rounded-t-[26px] border border-b-0 bg-white px-5 pt-3.5 pb-9'

export function useAnswer(runId: string, questionId: string) {
  const [sending, setSending] = useState(false)

  const send = (answers: string[], note = '') => {
    setSending(true)
    api.answer(runId, questionId, answers, note).catch((e: unknown) => {
      setSending(false)
      reportError(e)
    })
  }

  return { sending, send }
}

type ComposerParts = {
  busy: boolean
  extras: ReactNode
  onStop: () => void
}

export function QuestionComposer({
  runId,
  question,
  tool,
  ...parts
}: ComposerParts & { runId: string; question: Question; tool?: ToolActivity }) {
  return question.kind === 'ask' ? (
    <AskComposer key={question.id} runId={runId} question={question} {...parts} />
  ) : (
    <ApprovalComposer key={question.id} runId={runId} question={question} tool={tool} {...parts} />
  )
}

function emptyComposer(target: EventTarget | null): boolean {
  if (!isEditableTarget(target)) return true
  return target instanceof HTMLTextAreaElement && target.value === ''
}

function AskComposer({
  runId,
  question,
  busy,
  extras,
  onStop,
}: ComposerParts & { runId: string; question: AskQuestion }) {
  const items = question.items
  const [step, setStep] = useState(0)
  const [picks, setPicks] = useState<string[][]>(() =>
    items.map((item) => (item.multiple ? [] : item.options.slice(0, 1).map((o) => o.label))),
  )
  const [typed, setTyped] = useState<string[]>(() => items.map(() => ''))
  const [draft, setDraft] = useState<{ text: string; at: number }>()
  const [collapsed, setCollapsed] = useState(false)
  const [error, setError] = useState<string>()
  const { sending, send } = useAnswer(runId, question.id)
  const item = items[step]
  const last = step === items.length - 1

  const toggle = (label: string) =>
    setPicks((all) =>
      all.map((p, i) => {
        if (i !== step) return p
        if (!item.multiple) return [label]
        return p.includes(label) ? p.filter((x) => x !== label) : [...p, label]
      }),
    )

  const goTo = (target: number) => {
    setStep(target)
    setDraft({ text: typed[target], at: Date.now() })
  }

  const submit = async (text: string) => {
    const answer = text || picks[step].join(ANSWER_JOINER)
    if (!answer) {
      setError('Pick an option or type an answer.')
      throw new Error('empty answer')
    }

    setError(undefined)
    const answers = items.map((_, i) =>
      i === step ? answer : typed[i] || picks[i].join(ANSWER_JOINER),
    )
    setTyped((all) => all.map((t, i) => (i === step ? text : t)))
    if (last) send(answers)
    else goTo(step + 1)
  }

  useWindowEvent('keydown', (e) => {
    if (sending || collapsed || !emptyComposer(e.target) || e.ctrlKey || e.metaKey || e.altKey)
      return

    const index = Number(e.key) - 1
    if (Number.isInteger(index) && index >= 0 && index < item.options.length) {
      e.preventDefault()
      toggle(item.options[index].label)
      return
    }

    if (item.multiple || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return
    e.preventDefault()
    const current = item.options.findIndex((o) => o.label === picks[step][0])
    const move = e.key === 'ArrowDown' ? 1 : -1
    const next = (current + move + item.options.length) % item.options.length
    toggle(item.options[next].label)
  })

  return (
    <div>
      <div className={DOCK_CLASS}>
        <DockHeader
          label={item.header || 'Question'}
          counter={items.length > 1 ? `${step + 1}/${items.length}` : undefined}
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
          onBack={step > 0 ? () => goTo(step - 1) : undefined}
        />
        <div className="text-fg mt-1 text-[14px] font-medium [overflow-wrap:anywhere]">
          {item.question}
        </div>
        {collapsed ? null : (
          <OptionList item={item} picked={picks[step]} disabled={sending} onPick={toggle} />
        )}
        {error ? <div className="text-danger mt-2 text-[12px]">{error}</div> : null}
      </div>
      <div className="relative">
        <Composer
          busy={busy}
          queueWhileBusy
          allowEmpty
          placeholder="Type your own answer, or leave this blank to use the selected option"
          draftKey={`answer-${question.id}-${step}`}
          draft={draft}
          onSend={submit}
          onStop={onStop}
          extras={extras}
          submitLabel={() => (sending ? 'Sending' : last ? 'Submit' : 'Next')}
        />
      </div>
    </div>
  )
}

function DockHeader({
  label,
  counter,
  collapsed,
  onToggle,
  onBack,
}: {
  label: string
  counter?: string
  collapsed: boolean
  onToggle: () => void
  onBack?: () => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted text-[12px] font-semibold">{label}</span>
      <div className="flex-1" />
      {onBack ? (
        <button
          type="button"
          title="Previous question"
          onClick={onBack}
          className="text-faint hover:text-fg flex size-6 items-center justify-center rounded-full"
        >
          <CaretLeftIcon className="size-3.5" />
        </button>
      ) : null}
      {counter ? <span className="text-faint text-[12px] tabular-nums">{counter}</span> : null}
      <button
        type="button"
        title={collapsed ? 'Show options' : 'Hide options'}
        onClick={onToggle}
        className="text-faint hover:text-fg flex size-6 items-center justify-center rounded-full"
      >
        <CaretDownIcon className={cn('size-3.5 transition-transform', collapsed && 'rotate-180')} />
      </button>
    </div>
  )
}

function OptionList({
  item,
  picked,
  disabled,
  onPick,
}: {
  item: QuestionItem
  picked: string[]
  disabled: boolean
  onPick: (label: string) => void
}) {
  return (
    <div className="-mx-2 mt-2 max-h-[40vh] scrollbar-thin space-y-0.5 overflow-y-auto">
      {item.options.map((option, index) => {
        const on = picked.includes(option.label)

        return (
          <button
            key={option.label}
            type="button"
            disabled={disabled}
            onClick={() => onPick(option.label)}
            className={cn(
              'flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left transition-colors',
              on ? 'bg-brand-soft' : 'hover:bg-raised',
            )}
          >
            {item.multiple ? (
              <span
                className={cn(
                  'flex size-4 shrink-0 items-center justify-center rounded border',
                  on ? 'border-brand bg-brand text-white' : 'border-line-strong',
                )}
              >
                {on ? <CheckIcon weight="bold" className="size-3" /> : null}
              </span>
            ) : null}
            <span className="min-w-0 flex-1">
              <span
                className={cn(
                  'block text-[13.5px] font-medium',
                  on ? 'text-brand-strong' : 'text-fg',
                )}
              >
                {option.label}
              </span>
              {option.description ? (
                <span className="text-muted block text-[12.5px]">{option.description}</span>
              ) : null}
            </span>
            {index < MAX_KEYED_OPTIONS ? (
              <span className="text-faint shrink-0 text-[11.5px] tabular-nums">{index + 1}</span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

function ApprovalComposer({
  runId,
  question,
  tool,
  busy,
  extras,
  onStop,
}: ComposerParts & { runId: string; question: ApprovalQuestion; tool?: ToolActivity }) {
  const { sending, send } = useAnswer(runId, question.id)
  const rejectRef = useRef<HTMLButtonElement>(null)

  useWindowEvent('keydown', (e) => {
    if (e.key !== 'Escape' || sending || !emptyComposer(e.target)) return
    e.preventDefault()
    rejectRef.current?.focus()
  })

  return (
    <div>
      <div className="border-line-strong relative -mb-6 overflow-hidden rounded-t-[26px] border border-b-0 bg-white pb-6">
        <div className="flex items-center gap-2 px-5 pt-3">
          <ShieldWarningIcon weight="fill" className="text-warn size-4 shrink-0" />
          <span className="text-warn text-[12.5px] font-semibold">Approval needed</span>
          {tool ? (
            <Chip className="max-w-[50%] truncate" tone="neutral">
              {tool.name}
            </Chip>
          ) : null}
          <div className="flex-1" />
          <CopyButton text={question.detail} variant="ghost" />
        </div>
        <div className="px-5 pt-1.5">
          <div className="text-fg text-[14.5px] font-semibold [overflow-wrap:anywhere]">
            {question.question}
          </div>
          {question.reason ? (
            <div className="text-muted mt-0.5 text-[12.5px]">Why it asked: {question.reason}</div>
          ) : null}
          <pre className="bg-canvas border-line text-fg mt-2.5 max-h-56 scrollbar-thin overflow-auto rounded-xl border px-3.5 py-2.5 font-mono text-[12px] leading-[19px] break-words whitespace-pre-wrap">
            {question.detail}
          </pre>
          <div className="mt-2.5 mb-3 flex items-center justify-end gap-1.5">
            <Button
              ref={rejectRef}
              variant="ghost"
              disabled={sending}
              onClick={() => send([REJECT])}
            >
              <XIcon weight="bold" className="size-3.5" /> Reject
            </Button>
            <Button
              variant="primary"
              busy={sending}
              disabled={sending}
              onClick={() => send([APPROVE])}
            >
              <CheckIcon weight="bold" className="size-3.5" />
              Approve
            </Button>
          </div>
        </div>
      </div>
      <div className="relative">
        <Composer
          busy={busy}
          queueWhileBusy
          allowEmpty
          placeholder="Optional: tell the agent what to do instead, then press Enter to reject. Enter on empty approves."
          draftKey={`approval-${question.id}`}
          onSend={(text) => (text ? send([REJECT], text) : send([APPROVE]))}
          onStop={onStop}
          extras={extras}
          submitLabel={(text) => (text ? 'Reject with note' : APPROVE)}
        />
      </div>
    </div>
  )
}

const DECISION = {
  approved: { label: 'Approved', icon: CheckIcon, tone: 'text-ok' },
  rejected: { label: 'Rejected', icon: XIcon, tone: 'text-danger' },
  open: { label: 'Not answered', icon: MinusIcon, tone: 'text-faint' },
}

function DecidedApproval({ question }: { question: ApprovalQuestion }) {
  const answer = question.answers?.[0]
  const decision =
    DECISION[answer === APPROVE ? 'approved' : answer === REJECT ? 'rejected' : 'open']

  return (
    <details className="group text-[12.5px]">
      <summary className="text-muted hover:text-fg flex cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden">
        <decision.icon weight="bold" className={cn('size-3.5 shrink-0', decision.tone)} />
        <span className="min-w-0 truncate">{question.question}</span>
        <span className={cn('shrink-0 font-medium', decision.tone)}>{decision.label}</span>
        <CaretRightIcon className="text-faint size-3 shrink-0 transition-transform group-open:rotate-90" />
      </summary>
      {question.note ? <div className="text-text mt-1.5 ml-5">Note: {question.note}</div> : null}
      <pre className="bg-raised text-fg mt-1.5 ml-5 max-h-48 scrollbar-thin overflow-auto rounded-xl px-3 py-2 font-mono text-[11.5px] leading-[18px] break-all whitespace-pre-wrap">
        {question.detail}
      </pre>
    </details>
  )
}

export function AnsweredQuestion({ question }: { question: Question }) {
  if (question.kind === 'approval') return <DecidedApproval question={question} />

  return (
    <div className="space-y-0.5 text-[12.5px]">
      {question.items.map((item, i) => {
        const answer = question.answers?.[i]

        return (
          <div key={i} className="text-muted [overflow-wrap:anywhere]">
            {item.question}{' '}
            <span className={answer ? 'text-fg font-medium' : 'text-faint'}>
              {answer ?? 'Not answered'}
            </span>
          </div>
        )
      })}
    </div>
  )
}
