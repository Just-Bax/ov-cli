import type { WalkRun, WalkStep, WalkStepStatus } from '@shared/types.ts'
import type { BadgeTone } from '@/components/common/ui'
import { Spinner } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

export const WORKING: WalkStepStatus[] = ['pending', 'running']

export const STATUS_TONE: Record<WalkStepStatus, string> = {
  pending: 'bg-raised text-muted',
  running: 'bg-brand-soft text-brand-strong',
  passed: 'bg-ok-soft text-ok',
  failed: 'bg-danger-soft text-danger',
  blocked: 'bg-warn-soft text-warn',
  error: 'bg-danger-soft text-danger',
  stopped: 'bg-raised text-muted',
}

export const STATUS_LABEL: Record<WalkStepStatus, string> = {
  pending: 'Waiting',
  running: 'Running',
  passed: 'Passed',
  failed: 'Failed',
  blocked: 'Blocked',
  error: 'Error',
  stopped: 'Stopped',
}

export const BAR_TONE: Record<WalkStepStatus, string> = {
  pending: 'bg-brand',
  running: 'bg-brand',
  passed: 'bg-ok',
  failed: 'bg-danger',
  blocked: 'bg-warn',
  error: 'bg-danger',
  stopped: 'bg-muted',
}

export const BADGE_TONE: Record<WalkStepStatus, BadgeTone> = {
  pending: 'brand',
  running: 'brand',
  passed: 'ok',
  failed: 'danger',
  blocked: 'warn',
  error: 'danger',
  stopped: 'neutral',
}

export type Counts = { total: number; done: number; passed: number; current?: WalkStep }

export function counts(run: WalkRun): Counts {
  return {
    total: run.steps.length,
    done: run.steps.filter((s) => !WORKING.includes(s.status)).length,
    passed: run.steps.filter((s) => s.status === 'passed').length,
    current: run.steps.find((s) => s.status === 'running'),
  }
}

export function StatusPill({ status }: { status: WalkStepStatus }) {
  return (
    <span
      className={cn('rounded-full px-2 py-0.5 text-[10.5px] font-semibold', STATUS_TONE[status])}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

export function StatusDot({ status }: { status: WalkStepStatus }) {
  return <span className={cn('size-2 shrink-0 rounded-full', BAR_TONE[status])} />
}

export function Progress({
  done,
  total,
  status,
}: {
  done: number
  total: number
  status: WalkStepStatus
}) {
  const pct = total ? Math.round((done / total) * 100) : 0

  return (
    <div className="bg-raised h-1.5 w-full overflow-hidden rounded-full">
      <div
        className={cn('h-full rounded-full transition-[width] duration-300', BAR_TONE[status])}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function StepCard({ run, step }: { run: WalkRun; step: WalkStep }) {
  return (
    <div className="border-line rounded-xl border p-3">
      <div className="flex items-center gap-2">
        <StatusPill status={step.status} />
        <span className="min-w-0 flex-1 text-[12.5px] font-medium">{step.text}</span>
        {step.status === 'running' ? <Spinner className="text-brand size-3.5" /> : null}
      </div>
      {step.action ? <div className="text-muted mt-1 text-[11.5px]">{step.action}</div> : null}
      {step.detail ? <div className="text-faint mt-0.5 text-[11.5px]">{step.detail}</div> : null}
      {step.screenshot ? (
        <a
          href={api.walkShotUrl(run.id, step.screenshot)}
          target="_blank"
          rel="noreferrer"
          className="mt-2 block"
        >
          <img
            src={api.walkShotUrl(run.id, step.screenshot)}
            alt=""
            className="border-line max-h-60 w-full rounded-lg border object-cover object-top"
          />
        </a>
      ) : null}
    </div>
  )
}
