import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  Sparkle as SparklesIcon,
} from '@phosphor-icons/react'
import type { GraphNode } from '@shared/types.ts'
import { FORMS, TYPES } from '@/components/map/meta'
import { Button } from '@/components/common/ui'
import { openDraft } from '@/lib/draft'

const ICON_BUTTON = 'bg-raised hover:bg-brand-soft hover:text-brand-strong'

export function ObjectActions({
  node,
  host,
  alias,
}: {
  node: GraphNode
  host: string
  alias: string
}) {
  const ask = () =>
    openDraft({
      prompt: `Explain the ${TYPES[node.type].label.toLowerCase()} "${node.name}" (id ${node.ref}) on ${host}: what it does, what triggers or feeds it, and what depends on it. Start with ov_map, then confirm on the instance.`,
      instance: alias,
    })

  return (
    <div className="flex items-center gap-1.5">
      <Button size="sm" variant="primary" className="min-w-0 flex-1" onClick={ask}>
        <SparklesIcon className="size-3.5" /> Ask the agent
      </Button>
      <a
        href={`https://${host}${FORMS[node.type]}${node.ref}`}
        target="_blank"
        rel="noreferrer"
        title="Open in OneVizion"
        aria-label="Open in OneVizion"
        className={`text-muted inline-flex size-8 shrink-0 items-center justify-center rounded-full transition-colors ${ICON_BUTTON}`}
      >
        <ArrowTopRightOnSquareIcon className="size-4" />
      </a>
    </div>
  )
}
