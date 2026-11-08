import { ArrowSquareOut as ArrowTopRightOnSquareIcon } from '@phosphor-icons/react'
import type { CaseLink, RunState, RunSummary } from '@shared/types.ts'
import { ActionsSkeleton, ComposerSkeleton } from '@/components/common/skeletons'
import { Dot, Page, Shimmer, Skeleton, SkeletonText, type Tone } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { isBrowserTool, OpenBrowserButton, ShowBrowserButton } from './BrowserPane'
import { CostPill } from './CostPill'
import { InstanceChips } from './InstanceChip'
import { RunMenu } from './RunMenu'
import { RUN_STATUS, StatusIcon } from './RunStatus'

const RUN_ACTION_WIDTHS = ['w-24', 'w-9']
const NOTHING_SPENT = { amount: 0, requests: 0 }

const TONE_TEXT: Record<Tone, string> = {
  brand: 'text-brand-strong',
  ok: 'text-ok',
  warn: 'text-warn',
  danger: 'text-danger',
  neutral: 'text-muted',
}

export function RunLoading() {
  return (
    <Page
      title={<Skeleton className="h-4 w-80" />}
      actions={<ActionsSkeleton widths={RUN_ACTION_WIDTHS} />}
      footer={<ComposerSkeleton />}
      subtitle={
        <>
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-3 w-24" />
        </>
      }
    >
      <div className="mx-auto max-w-[860px] space-y-5 px-6 py-6">
        <div className="flex justify-end">
          <Skeleton className="h-9 w-56 rounded-2xl" />
        </div>
        <Skeleton className="h-9 w-full rounded-full" />
        <SkeletonText lines={2} />
        <Skeleton className="h-9 w-full rounded-full" />
        <SkeletonText lines={4} />
      </div>
    </Page>
  )
}

function CaseLinks({ cases }: { cases: CaseLink[] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5">
      <span className="text-muted">{cases.length === 1 ? 'Case' : 'Cases'}</span>
      {cases.map((c) => (
        <a
          key={c.key}
          href={c.url}
          target="_blank"
          rel="noreferrer"
          className="text-brand-strong inline-flex items-center gap-0.5 whitespace-nowrap hover:underline"
        >
          {c.key}
          <ArrowTopRightOnSquareIcon className="size-3" />
        </a>
      ))}
    </span>
  )
}

export function RunSubtitle({ state, browsing }: { state: RunState; browsing: boolean }) {
  const { summary } = state
  const status = RUN_STATUS[summary.status]

  return (
    <>
      {summary.status === 'running' || summary.status === 'queued' ? (
        <Shimmer tone="brand" className="font-medium">
          {status.text}
        </Shimmer>
      ) : (
        <span
          className={cn('inline-flex items-center gap-1.5 font-medium', TONE_TEXT[status.tone])}
        >
          <StatusIcon status={summary.status} className="size-3" detailed />
          {status.text}
        </span>
      )}
      {state.cases.length && !browsing ? (
        <>
          <Dot />
          <CaseLinks cases={state.cases} />
        </>
      ) : null}
      {state.instances.length > 0 && !browsing ? (
        <>
          <Dot />
          <InstanceChips instances={state.instances} />
        </>
      ) : null}
    </>
  )
}

export function RunActions({
  runId,
  state,
  run,
  settled,
  busy,
  browsing,
  onShowBrowser,
}: {
  runId: string
  state: RunState
  run: RunSummary
  settled: boolean
  busy: boolean
  browsing: boolean
  onShowBrowser: () => void
}) {
  const { summary } = state
  const browser = state.browser?.open ? state.browser : undefined
  const lastInstance = state.instances.at(-1)

  return (
    <>
      {browser && !browsing ? (
        <ShowBrowserButton
          instance={browser.instance ?? ''}
          driving={isBrowserTool(state.tools.findLast((t) => t.status === 'running')?.name)}
          onShow={onShowBrowser}
        />
      ) : null}
      {lastInstance && !browser ? (
        <OpenBrowserButton runId={runId} instance={lastInstance} />
      ) : null}
      <CostPill
        runId={runId}
        provider={summary.provider}
        cost={summary.cost ?? (busy || summary.origin === 'branch' ? NOTHING_SPENT : undefined)}
        context={state.context}
        counting={summary.status === 'running'}
      />
      <RunMenu run={run} settled={settled} />
    </>
  )
}
