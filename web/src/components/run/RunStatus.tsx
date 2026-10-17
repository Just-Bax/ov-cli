import {
  CheckCircle as CheckCircleIcon,
  WarningCircle as ExclamationCircleIcon,
  Prohibit as NoSymbolIcon,
} from '@phosphor-icons/react'
import type { RunStatus } from '@shared/types.ts'
import { PulseDot, type Tone } from '@/components/common/ui'
import { cn } from '@/lib/cn'

export const RUN_STATUS: Record<RunStatus, { text: string; tone: Tone }> = {
  queued: { text: 'Starting', tone: 'brand' },
  running: { text: 'Working', tone: 'brand' },
  waiting: { text: 'Needs you', tone: 'warn' },
  done: { text: 'Done', tone: 'ok' },
  error: { text: 'Failed', tone: 'danger' },
  cancelled: { text: 'Stopped', tone: 'neutral' },
}

const STATUS_DOT: Partial<Record<RunStatus, string>> = {
  waiting: 'bg-warn',
  error: 'bg-danger',
  cancelled: 'bg-line-strong',
  done: 'bg-ok',
}

export function StatusIcon({
  status,
  className,
  detailed,
}: {
  status: RunStatus
  className?: string
  detailed?: boolean
}) {
  if (status === 'running' || status === 'queued') return <PulseDot className={className} />
  if (detailed && status === 'done')
    return <CheckCircleIcon className={cn('text-ok size-3.5', className)} />
  if (detailed && status === 'cancelled')
    return <NoSymbolIcon className={cn('text-faint size-3.5', className)} />
  if (detailed && status === 'error')
    return <ExclamationCircleIcon className={cn('text-danger size-3.5', className)} />

  return <span className={cn('block size-1.5 rounded-full', STATUS_DOT[status], className)} />
}
