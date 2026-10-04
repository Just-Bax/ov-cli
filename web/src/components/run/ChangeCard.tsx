import { ExternalLink } from 'lucide-react'
import type { Change } from '@shared/types.ts'
import { Button, Chip, CopyButton } from '@/components/ui'
import { Diff } from './Diff'

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
          <div className="flex items-center gap-2">
            <Chip tone="brand">{change.entityType}</Chip>
            <span className="text-fg truncate text-[13.5px] font-semibold">{change.title}</span>
          </div>
          {meta.length ? (
            <div className="text-muted mt-1 truncate text-[12px]">{meta.join(' - ')}</div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {change.link ? (
            <a href={change.link} target="_blank" rel="noreferrer">
              <Button size="sm" variant="ghost">
                <ExternalLink className="size-3.5" /> Open {change.entityType.split(' ')[0]}
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
