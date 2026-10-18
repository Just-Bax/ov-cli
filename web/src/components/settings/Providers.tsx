import { ArrowsClockwise as ArrowPathIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Provider, Status } from '@shared/types.ts'
import { PROVIDER_NAMES, ProviderLogo } from '@/components/common/ProviderLogo'
import { reportError } from '@/components/common/Toasts'
import { Select, Shimmer } from '@/components/common/ui'
import { CopilotSignIn } from '@/components/settings/CopilotSignIn'
import { api } from '@/lib/api'

const PROVIDERS: Provider[] = ['claude', 'copilot']

export function planLabel(plan?: string): string {
  return plan ? `${plan[0].toUpperCase()}${plan.slice(1)} plan` : 'Claude plan'
}

export function providerReady(status: Status, provider: Provider): boolean {
  return provider === 'claude' ? status.claude.signedIn : status.copilot.signedIn
}

export function providerSummary(status: Status): string {
  if (status.provider === 'copilot')
    return status.copilot.signedIn
      ? `GitHub as ${status.copilot.user}, paid in Copilot credits.`
      : 'Not signed in to GitHub.'

  if (!status.claude.installed) return 'Claude Code is not installed.'

  return status.claude.signedIn
    ? `Claude Code as ${status.claude.email}, ${planLabel(status.claude.plan)}.`
    : 'Claude Code is not signed in.'
}

export function ProviderSelect({
  value,
  onChange,
  className,
}: {
  value: Provider
  onChange: (provider: Provider) => void
  className?: string
}) {
  return (
    <Select
      className={className}
      value={value}
      onChange={(v) => onChange(v as Provider)}
      options={PROVIDERS.map((p) => ({
        value: p,
        label: PROVIDER_NAMES[p],
        icon: <ProviderLogo provider={p} className="size-4" />,
      }))}
    />
  )
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

export function ProviderSetup({ status, onRefresh }: { status: Status; onRefresh: () => void }) {
  if (providerReady(status, status.provider)) return null
  if (status.provider === 'copilot') return <CopilotSignIn onDone={onRefresh} />

  return (
    <div className="bg-raised text-muted rounded-2xl px-4 py-3 text-[12.5px] leading-relaxed">
      {status.claude.installed ? null : 'Install Claude Code, then '}
      {status.claude.installed ? 'Run ' : 'run '}
      <code>claude</code> in a terminal and sign in with <code>/login</code>. OV Agent uses that
      sign-in and never sees your password or token. <CheckAgain onRefresh={onRefresh} />
    </div>
  )
}
