import { ArrowClockwise as RecheckIcon } from '@phosphor-icons/react'
import type { Instance } from '@shared/types.ts'
import { Shimmer } from '@/components/common/ui'
import { cn } from '@/lib/cn'
import { allowedLabels, editionLabel } from '@/lib/instances'

const NOT_ALLOWED = 'This account cannot use it on this instance'
const RECHECK = 'Check what this account can use again'

function CheckButton({ label, onCheck }: { label: string; onCheck: () => void }) {
  return (
    <button
      type="button"
      onClick={onCheck}
      className="text-brand-strong inline-flex items-center gap-1 font-medium hover:underline"
    >
      <RecheckIcon className="size-3" /> {label}
    </button>
  )
}

export function PlatformLabel({ instance }: { instance: Instance }) {
  const { access } = instance
  const platform = [editionLabel(access), access.version].filter(Boolean).join(' ')
  if (!platform || access.checking || access.error) return null

  return (
    <span title={platform} className="text-muted min-w-0 shrink truncate text-[11.5px]">
      {platform}
    </span>
  )
}

export function AccessLine({ instance, onCheck }: { instance: Instance; onCheck: () => void }) {
  const { access } = instance

  if (access.checking) {
    return (
      <div className="mt-0.5 text-[11.5px]">
        <Shimmer>Checking what this account can use</Shimmer>
      </div>
    )
  }

  if (access.error) {
    return (
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11.5px]">
        <span className="text-danger">{access.error}</span>
        {instance.valid ? <CheckButton label="Check again" onCheck={onCheck} /> : null}
      </div>
    )
  }

  if (!access.checkedAt) {
    return (
      <div className="text-faint mt-0.5 flex items-center gap-2 text-[11.5px]">
        {instance.valid ? (
          <>
            Access not checked yet.
            <CheckButton label="Check" onCheck={onCheck} />
          </>
        ) : (
          'Access not checked yet. Sign in to check it.'
        )}
      </div>
    )
  }

  const recheck = instance.valid ? (
    <button
      type="button"
      title={RECHECK}
      aria-label={RECHECK}
      onClick={onCheck}
      className="text-faint hover:text-brand-strong grid size-5 place-items-center rounded-full"
    >
      <RecheckIcon className="size-3" />
    </button>
  ) : null

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px]">
      {allowedLabels(access).map(({ label, on }) => (
        <span
          key={label}
          title={on ? undefined : NOT_ALLOWED}
          className={cn(
            'rounded-full px-2 py-px font-medium whitespace-nowrap',
            on ? 'bg-ok-soft text-ok' : 'bg-canvas text-faint line-through',
          )}
        >
          {label}
        </span>
      ))}
      {recheck}
    </div>
  )
}
