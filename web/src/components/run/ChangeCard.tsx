import { ArrowSquareOut as ArrowTopRightOnSquareIcon } from '@phosphor-icons/react'
import type { Change } from '@shared/types.ts'
import { Button, CopyButton } from '@/components/common/ui'
import { Diff } from './Diff'

const TYPE_LABELS: Record<string, string> = { 'db package': 'DB package' }

function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? `${type.charAt(0).toUpperCase()}${type.slice(1)}`
}

export function ChangeCard({ change }: { change: Change }) {
  const meta = [
    change.entityName,
    change.entityId && `ID ${change.entityId}`,
    change.instance,
  ].filter(Boolean)

  return (
    <div className="border-line-strong/70 overflow-hidden rounded-2xl border">
      <div className="bg-raised flex items-start gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13.5px] leading-snug font-semibold">{change.title}</div>
          <div className="text-muted mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[12px]">
            <span className="text-brand-strong max-w-[220px] truncate font-medium">
              {typeLabel(change.entityType)}
            </span>
            {meta.map((part) => (
              <span key={part} className="flex min-w-0 items-center gap-1.5">
                <span className="text-faint">/</span>
                <span className="truncate">{part}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {change.link ? (
            <a href={change.link} target="_blank" rel="noreferrer">
              <Button size="sm" variant="ghost">
                <ArrowTopRightOnSquareIcon className="size-3.5" /> Open
              </Button>
            </a>
          ) : null}
          <CopyButton text={change.after} label="Copy fix" />
        </div>
      </div>
      <dl className="border-line grid gap-x-3 gap-y-1 border-t px-4 py-2.5 text-[12.5px] sm:grid-cols-[48px_1fr]">
        <dt className="text-faint">What</dt>
        <dd className="text-text">{change.what}</dd>
        <dt className="text-faint">Why</dt>
        <dd className="text-text">{change.why}</dd>
        <dt className="text-faint">How</dt>
        <dd className="text-text">{change.how}</dd>
      </dl>
      <div className="border-line border-t">
        <Diff before={change.before} after={change.after} />
      </div>
    </div>
  )
}
