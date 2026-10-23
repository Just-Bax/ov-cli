import {
  SignOut as ArrowRightStartOnRectangleIcon,
  ArrowsClockwise as ArrowPathIcon,
} from '@phosphor-icons/react'
import type { CopilotUser, ProviderAccount } from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { reportError } from '@/components/common/Toasts'
import { Button, GithubBadge, IconButton, Skeleton } from '@/components/common/ui'
import { CopilotSignIn } from '@/components/settings/CopilotSignIn'
import { api } from '@/lib/api'
import { formatCredits } from '@/lib/cost'
import { useLoad } from '@/lib/hooks'
import { go } from '@/lib/route'
import { capitalized, PlanRow, type ProviderUi } from './parts'

const GITHUB_URL = 'https://github.com'
const AVATAR_PX = 64

function copilotOf(account: ProviderAccount): CopilotUser {
  return account as CopilotUser
}

function resetDay(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString([], { month: 'long', day: 'numeric' })
}

function CopilotPlan() {
  const { value: account, loading, reload } = useLoad(api.copilotAccount, [])
  const skeleton = useSkeleton(loading)
  const detail = !account
    ? 'Usage could not be read from GitHub.'
    : account.tokenBased
      ? `${formatCredits(account.creditsUsed ?? 0)} credits used this cycle across all your Copilot use${
          account.resetDate ? `, resets ${resetDay(account.resetDate)}.` : '.'
        }`
      : account.unlimited
        ? 'Unlimited premium requests.'
        : `${(account.entitlement ?? 0) - (account.remaining ?? 0)} of ${account.entitlement ?? 0} premium requests used this cycle.`

  return (
    <PlanRow
      title={
        account
          ? `GitHub Copilot, ${account.plan ? `${capitalized(account.plan)} plan` : 'Copilot'}`
          : 'GitHub Copilot'
      }
      action={
        <IconButton label="Refresh" busy={loading} disabled={loading} onClick={reload}>
          <ArrowPathIcon className="size-4" />
        </IconButton>
      }
    >
      {skeleton ? <Skeleton className="mt-1 h-2.5 w-72" /> : detail}
    </PlanRow>
  )
}

function SignOut({ account, onChange }: { account: ProviderAccount; onChange: () => void }) {
  if (!copilotOf(account).signedIn) return null

  const signOut = async () => {
    await api.copilotLogout()
    go({ page: 'home' })
    onChange()
  }

  return (
    <Button size="sm" variant="danger" onClick={() => void signOut().catch(reportError)}>
      <ArrowRightStartOnRectangleIcon className="size-3.5" /> Sign out
    </Button>
  )
}

export const COPILOT_UI: ProviderUi = {
  usageTitle: 'Copilot usage',
  usageNote: "Credits Copilot charged for this app's requests.",
  accountBadge: <GithubBadge />,
  summary: (account) => {
    const { signedIn, user } = copilotOf(account)
    return signedIn ? `GitHub as ${user}, paid in Copilot credits.` : 'Not signed in to GitHub.'
  },
  sidebar: (account) => {
    const { user } = copilotOf(account)
    return {
      name: user ?? undefined,
      detail: 'GitHub Copilot',
      imageUrl: user
        ? `${GITHUB_URL}/${encodeURIComponent(user)}.png?size=${AVATAR_PX}`
        : undefined,
    }
  },
  accountDetail: (account, runsAgent) => {
    const { user } = copilotOf(account)
    return user ? `Signed in as ${user}.${runsAgent ? ' Runs the agent.' : ''}` : 'Not signed in'
  },
  SignIn: ({ onRefresh }) => <CopilotSignIn onDone={onRefresh} />,
  Plan: CopilotPlan,
  AccountAction: SignOut,
}
