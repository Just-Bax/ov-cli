import { ClockIcon, KeyIcon, PaperAirplaneIcon } from '@heroicons/react/24/outline'
import { formatMinutes } from '@shared/estimate.ts'
import { useState } from 'react'
import type { LoginPrompt, Outcome, Question, Verdict } from '@shared/types.ts'
import { Button, Chip, CopyButton, Input, Markdown, Spinner, type Tone } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useSettings } from '@/lib/settings'
import { reportError } from '@/components/Toasts'

const VERDICT: Record<Verdict, { label: string; tone: Tone }> = {
  fix: { label: 'Fix needed', tone: 'warn' },
  fixed: { label: 'Fixed', tone: 'ok' },
  user_action: { label: 'User action', tone: 'brand' },
  expected: { label: 'Expected behavior', tone: 'ok' },
  info: { label: 'Finding', tone: 'brand' },
  unknown: { label: 'Unclear', tone: 'neutral' },
}

const COVERS: Record<string, { label: string; tone: Tone }> = {
  yes: { label: 'Covers it', tone: 'ok' },
  partly: { label: 'Partly', tone: 'warn' },
  no: { label: 'Not covered', tone: 'neutral' },
}

export function Answer({ outcome, caseUrl }: { outcome: Outcome; caseUrl?: string }) {
  const { settings } = useSettings()

  return (
    <div className="space-y-3">
      <div className="border-line-strong/70 divide-line divide-y overflow-hidden rounded-2xl border">
        {outcome.issues.map((issue, i) => (
          <div key={i} className="px-4 py-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip tone={VERDICT[issue.verdict]?.tone ?? 'neutral'}>
                {VERDICT[issue.verdict]?.label ?? issue.verdict}
              </Chip>
              {issue.stillHappening !== undefined ? (
                <Chip tone={issue.stillHappening ? 'danger' : 'neutral'}>
                  {issue.stillHappening ? 'Still happening' : 'Not happening now'}
                </Chip>
              ) : null}
              <span className="text-fg ml-1 text-[13.5px] font-semibold">{issue.title}</span>
            </div>
            <div className="text-text mt-1.5 text-[13.5px] leading-relaxed">
              <Markdown text={issue.summary} />
            </div>
            {issue.evidence?.length ? (
              <ul className="text-muted mt-1.5 space-y-0.5 text-[12px]">
                {issue.evidence.map((e, j) => (
                  <li key={j} className="flex gap-2">
                    <span className="bg-line-strong mt-[7px] size-1 shrink-0 rounded-full" />
                    <span className="min-w-0 flex-1">
                      <Markdown text={e} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
        {outcome.existing?.length ? (
          <div className="px-4 py-3">
            <div className="text-faint mb-1.5 text-[11.5px] font-medium">Existing issues</div>
            {outcome.existing.map((e, i) => (
              <div key={i} className="flex items-center gap-2 py-0.5 text-[12.5px]">
                <Chip tone={COVERS[e.covers]?.tone ?? 'neutral'}>
                  {COVERS[e.covers]?.label ?? e.covers}
                </Chip>
                {e.link ? (
                  <a
                    href={e.link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-brand-strong shrink-0 font-medium hover:underline"
                  >
                    {e.key}
                  </a>
                ) : (
                  <span className="shrink-0 font-medium">{e.key}</span>
                )}
                <span className="text-text min-w-0 flex-1 truncate">{e.title}</span>
              </div>
            ))}
          </div>
        ) : null}
        {outcome.unrelated.length ? (
          <details className="px-4 py-2.5">
            <summary className="text-muted cursor-pointer text-[12px]">
              {outcome.unrelated.length} unrelated finding
              {outcome.unrelated.length === 1 ? '' : 's'}
            </summary>
            <ul className="text-text mt-1.5 list-disc space-y-0.5 pl-5 text-[12.5px]">
              {outcome.unrelated.map((u, i) => (
                <li key={i}>
                  <Markdown text={u} />
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      {outcome.reply ? (
        <div className="border-brand/40 bg-brand-soft/50 rounded-2xl border">
          <div className="flex items-center gap-2 px-4 pt-2.5">
            <span className="text-brand-strong text-[12px] font-semibold">
              {caseUrl ? 'Reply for the case chat' : 'Message to share'}
            </span>
            <div className="flex-1" />
            {caseUrl ? (
              <a
                href={caseUrl}
                target="_blank"
                rel="noreferrer"
                className="text-brand-strong text-[12px] hover:underline"
              >
                Open case
              </a>
            ) : null}
            <CopyButton text={outcome.reply} label="Copy" variant="primary" />
          </div>
          <div className="text-fg px-4 pt-1.5 pb-3 text-[13.5px] leading-relaxed">
            <Markdown text={outcome.reply} />
          </div>
        </div>
      ) : null}
      {settings.showTimeSaved && outcome.timeSaved?.minutes ? (
        <div className="text-muted flex items-start gap-1.5 px-1 text-[12px]">
          <ClockIcon className="text-ok mt-0.5 size-3.5 shrink-0" />
          <span>
            <span className="text-ok font-medium">
              ~{formatMinutes(outcome.timeSaved.minutes)} saved.
            </span>{' '}
            {outcome.timeSaved.basis}
          </span>
        </div>
      ) : null}
    </div>
  )
}

function ApprovalCard({ runId, question }: { runId: string; question: Question }) {
  const [sending, setSending] = useState(false)
  const answered = question.answer !== undefined
  const approved = question.answer === 'Approve'

  const send = async (answer: string) => {
    setSending(true)
    await api.answer(runId, question.id, answer).catch((e: Error) => {
      setSending(false)
      reportError(e)
    })
  }

  return (
    <div
      className={cn(
        'rounded-2xl border',
        answered ? 'border-line' : 'border-warn/50 bg-warn-soft/30',
      )}
    >
      <div className="flex items-center gap-2 px-4 pt-3">
        <KeyIcon className={cn('size-4', answered ? 'text-faint' : 'text-warn')} />
        <span className="text-fg flex-1 text-[13.5px] font-medium">{question.question}</span>
        {answered ? (
          <span className={cn('text-[12px] font-medium', approved ? 'text-ok' : 'text-danger')}>
            {approved ? 'Approved' : 'Rejected'}
          </span>
        ) : null}
      </div>
      <pre className="bg-raised text-fg mx-4 my-2.5 max-h-48 scrollbar-thin overflow-auto rounded-2xl px-3 py-2 font-mono text-[11.5px] leading-[18px] break-all whitespace-pre-wrap">
        {question.detail}
      </pre>
      {!answered ? (
        <div className="flex justify-end gap-1.5 px-4 pb-3">
          <Button variant="ghost" disabled={sending} onClick={() => void send('Reject')}>
            Reject
          </Button>
          <Button variant="primary" disabled={sending} onClick={() => void send('Approve')}>
            {sending ? <Spinner className="size-3.5" /> : null} Approve
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function QuestionCard({ runId, question }: { runId: string; question: Question }) {
  const [picked, setPicked] = useState<string[]>([])
  const [other, setOther] = useState('')
  const [sending, setSending] = useState(false)

  if (question.detail) return <ApprovalCard runId={runId} question={question} />

  if (question.answer !== undefined) {
    return (
      <div className="text-muted text-[12.5px]">
        {question.question} <span className="text-fg font-medium">{question.answer}</span>
      </div>
    )
  }

  const send = async (answer: string) => {
    setSending(true)
    await api.answer(runId, question.id, answer).catch((e: Error) => {
      setSending(false)
      reportError(e)
    })
  }

  return (
    <div className="border-warn/50 bg-warn-soft/40 rounded-2xl border px-4 py-3">
      <div className="text-fg text-[13.5px] font-medium">{question.question}</div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {question.options.map((o) => {
          const on = picked.includes(o)

          return (
            <button
              key={o}
              type="button"
              disabled={sending}
              onClick={() =>
                question.multiple
                  ? setPicked(on ? picked.filter((p) => p !== o) : [...picked, o])
                  : void send(o)
              }
              className={cn(
                'h-8 rounded-full border px-3.5 text-[12.5px] transition-colors',
                on
                  ? 'border-brand bg-brand-soft text-brand-strong'
                  : 'border-line-strong hover:border-brand bg-white',
              )}
            >
              {o}
            </button>
          )
        })}
      </div>
      <form
        className="mt-2 flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          const answer = [...picked, other.trim()].filter(Boolean).join('; ')
          if (answer) void send(answer)
        }}
      >
        <Input
          value={other}
          onChange={(e) => setOther(e.target.value)}
          placeholder="Or type an answer"
          className="bg-white"
        />
        <Button
          type="submit"
          variant="primary"
          disabled={sending || (!other.trim() && !picked.length)}
        >
          {sending ? <Spinner className="size-3.5" /> : <PaperAirplaneIcon className="size-3.5" />}
        </Button>
      </form>
    </div>
  )
}

export function LoginCard({ runId, login }: { runId: string; login: LoginPrompt }) {
  if (login.state === 'done') {
    return (
      <div className="text-muted text-[12.5px]">
        Signed in to {login.instance}
        {login.tenant ? `, tenant ${login.tenant}` : ''}.
      </div>
    )
  }

  return (
    <div className="border-warn/50 bg-warn-soft/40 flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-3">
      <KeyIcon className="text-warn size-4" />
      <div className="min-w-0 flex-1">
        <div className="text-fg flex flex-wrap items-center gap-1.5 text-[13.5px] font-medium">
          Sign in to {login.instance}
          {login.tenant ? <Chip tone="brand">{login.tenant}</Chip> : null}
        </div>
        <div className="text-muted text-[12px]">
          {login.state === 'running'
            ? login.tenant
              ? `Finish signing in in the browser window that opened. You land in your own tenant; ov then switches to ${login.tenant} for you.`
              : 'Finish signing in in the browser window that opened. It closes on its own.'
            : login.state === 'failed'
              ? (login.message ?? 'Sign-in failed.')
              : login.tenant
                ? `Needed to continue. Sign in as usual; ov switches to ${login.tenant} afterwards. Access is read-only.`
                : 'Needed to continue. A browser window opens on the login page. Access is read-only.'}
        </div>
      </div>
      {login.state === 'running' ? (
        <Spinner className="text-brand" />
      ) : (
        <>
          <Button variant="ghost" onClick={() => void api.login(runId, login.id, true)}>
            Skip
          </Button>
          <Button variant="primary" onClick={() => void api.login(runId, login.id)}>
            {login.state === 'failed' ? 'Try again' : 'Sign in'}
          </Button>
        </>
      )}
    </div>
  )
}
