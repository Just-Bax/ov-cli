import { ArrowsClockwise as ArrowPathIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { ClaudeAccount, ProviderAccount } from '@shared/types.ts'
import { ProviderBubble } from '@/components/common/ProviderLogo'
import { useSkeleton } from '@/components/common/skeletons'
import { reportError } from '@/components/common/Toasts'
import { IconButton, Shimmer, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { useLoad } from '@/lib/hooks'
import { capitalized, PlanRow, type ProviderUi } from './parts'

function planLabel(plan?: string): string {
  return plan ? `${capitalized(plan)} plan` : 'Claude plan'
}

function claudeOf(account: ProviderAccount): ClaudeAccount {
  return account as ClaudeAccount
}

function CheckAgain({ onRefresh }: { onRefresh: () => void }) {
  const [checking, setChecking] = useState(false)

  return (
    <button
      type="button"
      disabled={checking}
      onClick={() => {
        setChecking(true)
        api
          .claudeAccount()
          .then(onRefresh, reportError)
          .finally(() => setChecking(false))
      }}
      className="text-brand-strong inline-flex items-center gap-1 font-medium hover:underline"
    >
      <ArrowPathIcon className="size-3" />
      {checking ? <Shimmer tone="brand">Checking</Shimmer> : 'Check again'}
    </button>
  )
}

function ClaudeSignIn({ account, onRefresh }: { account: ProviderAccount; onRefresh: () => void }) {
  const { installed } = claudeOf(account)

  return (
    <div className="bg-raised text-muted rounded-2xl px-4 py-3 text-[12.5px] leading-relaxed">
      {installed ? null : 'Install Claude Code, then '}
      {installed ? 'Run ' : 'run '}
      <code>claude</code> in a terminal and sign in with <code>/login</code>. OV Agent uses that
      sign-in and never sees your password or token. <CheckAgain onRefresh={onRefresh} />
    </div>
  )
}

function ClaudePlan() {
  const { value: account, loading, reload } = useLoad(api.claudeAccount, [])
  const skeleton = useSkeleton(loading)

  return (
    <PlanRow
      title={account?.signedIn ? `Claude, ${planLabel(account.plan)}` : 'Claude'}
      action={
        <IconButton label="Refresh" busy={loading} disabled={loading} onClick={reload}>
          <ArrowPathIcon className="size-4" />
        </IconButton>
      }
    >
      {skeleton || !account ? (
        <Skeleton className="mt-1 h-2.5 w-72" />
      ) : account.signedIn ? (
        `Signed in to Claude Code as ${account.email}.`
      ) : (
        'Claude Code is not signed in on this computer.'
      )}
    </PlanRow>
  )
}

export const CLAUDE_UI: ProviderUi = {
  usageTitle: 'Claude plan usage, estimated',
  usageNote:
    "Claude Code's estimate of what the same requests would cost on the API. Your plan is not billed per request.",
  accountBadge: <ProviderBubble provider="claude" className="size-10" />,
  summary: (account) => {
    const { installed, signedIn, email, plan } = claudeOf(account)
    if (!installed) return 'Claude Code is not installed.'
    return signedIn
      ? `Claude Code as ${email}, ${planLabel(plan)}.`
      : 'Claude Code is not signed in.'
  },
  plan: (account) => {
    const { signedIn, plan } = claudeOf(account)
    if (!signedIn) return 'Not signed in'
    return plan ? `${capitalized(plan)} plan` : 'Signed in'
  },
  accountDetail: (account, runsAgent) => {
    const { signedIn, email } = claudeOf(account)
    if (!signedIn) return 'Not signed in to Claude Code'
    return `Signed in as ${email}.${runsAgent ? ' Runs the agent.' : ''} Sign out with /logout.`
  },
  SignIn: ClaudeSignIn,
  Plan: ClaudePlan,
}
