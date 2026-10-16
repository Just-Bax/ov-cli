import { Key as KeyIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { LoginPrompt, Outcome, Verdict } from '@shared/types.ts'
import { Button, Chip, CopyButton, Markdown, Spinner, type Tone } from '@/components/common/ui'
import { api } from '@/lib/api'
import { reportError } from '@/components/common/Toasts'
import { SignInModal, type SignInTarget } from '@/components/signin/SignInModal'

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
    </div>
  )
}

export function LoginCard({ runId, login }: { runId: string; login: LoginPrompt }) {
  const [open, setOpen] = useState(false)
  const target: SignInTarget = { url: login.url, host: login.instance, tenant: login.tenant }

  if (login.state === 'done' || login.state === 'skipped') {
    return (
      <div className="text-muted flex items-center gap-1.5 text-[12.5px]">
        <KeyIcon className="text-faint size-3.5" />
        {login.state === 'done' ? 'Signed in to' : 'Skipped sign-in to'} {login.instance}
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
            ? 'Signing in. Open the sign-in window to continue.'
            : login.state === 'failed'
              ? (login.message ?? 'Sign-in failed.')
              : login.tenant
                ? `Needed to continue. Sign in as usual; ov switches to ${login.tenant} afterwards. Access is read-only.`
                : 'Needed to continue. Access is read-only.'}
        </div>
      </div>
      {login.state === 'running' ? (
        <>
          <Spinner className="text-brand" />
          {open ? null : (
            <Button variant="ghost" onClick={() => setOpen(true)}>
              Show
            </Button>
          )}
        </>
      ) : (
        <>
          <Button
            variant="ghost"
            onClick={() => void api.login(runId, login.id, { skip: true }).catch(reportError)}
          >
            Skip
          </Button>
          <Button variant="primary" onClick={() => setOpen(true)}>
            {login.state === 'failed' ? 'Try again' : 'Sign in'}
          </Button>
        </>
      )}
      <SignInModal
        target={open ? target : undefined}
        pending={login.state === 'running'}
        onClose={() => setOpen(false)}
        onStart={() => undefined}
        onFinished={() => undefined}
        submit={(_, token, screen) => api.login(runId, login.id, { token, screen })}
      />
    </div>
  )
}
