import {
  ArrowTopRightOnSquareIcon,
  CodeBracketIcon,
  DocumentMagnifyingGlassIcon,
  MapIcon,
  SparklesIcon,
} from '@heroicons/react/24/outline'
import type { GraphNode } from '@shared/types.ts'
import { FORMS, TYPES, WITH_CODE } from '@/components/map/meta'
import { Button, IconButton } from '@/components/ui'
import { openDraft } from '@/lib/draft'
import { go } from '@/lib/route'
import { EXPLORE_KEY, FOCUS_KEY } from '@/lib/useInstanceGraph'

const ICON_BUTTON = 'bg-raised hover:bg-brand-soft hover:text-brand-strong'

export function ObjectActions({
  node,
  host,
  alias,
  page,
  onExplore,
  onReview,
}: {
  node: GraphNode
  host: string
  alias: string
  page: 'map' | 'explorer'
  onExplore?: () => void
  onReview?: () => void
}) {
  const explorable = WITH_CODE.has(node.type) && (page !== 'explorer' || onExplore)

  const ask = () =>
    openDraft({
      prompt: `Explain the ${TYPES[node.type].label.toLowerCase()} "${node.name}" (id ${node.ref}) on ${host}: what it does, what triggers or feeds it, and what depends on it. Start with ov_map, then confirm on the instance.`,
      instance: alias,
    })

  const explore = () => {
    if (onExplore) return onExplore()
    localStorage.setItem(EXPLORE_KEY, node.id)
    go({ page: 'explorer' })
  }

  const showOnMap = () => {
    localStorage.setItem(FOCUS_KEY, node.id)
    go({ page: 'map' })
  }

  return (
    <div className="flex items-center gap-1.5">
      <Button size="sm" variant="primary" className="min-w-0 flex-1" onClick={ask}>
        <SparklesIcon className="size-3.5" /> Ask the agent
      </Button>
      {onReview ? (
        <Button size="sm" variant="secondary" onClick={onReview}>
          <DocumentMagnifyingGlassIcon className="size-3.5" /> Review
        </Button>
      ) : null}
      {explorable ? (
        <IconButton label="Open in Explorer" className={ICON_BUTTON} onClick={explore}>
          <CodeBracketIcon className="size-4" />
        </IconButton>
      ) : null}
      {page !== 'map' ? (
        <IconButton label="Show on map" className={ICON_BUTTON} onClick={showOnMap}>
          <MapIcon className="size-4" />
        </IconButton>
      ) : null}
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
