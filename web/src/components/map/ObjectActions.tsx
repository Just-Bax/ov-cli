import {
  ArrowTopRightOnSquareIcon,
  CodeBracketIcon,
  MapIcon,
  SparklesIcon,
} from '@heroicons/react/24/outline'
import type { GraphNode } from '@shared/types.ts'
import { FORMS, TYPES, WITH_CODE } from '@/components/map/meta'
import { Button } from '@/components/ui'
import { openDraft } from '@/lib/draft'
import { go } from '@/lib/route'
import { EXPLORE_KEY, FOCUS_KEY } from '@/lib/useInstanceGraph'

export function ObjectActions({
  node,
  host,
  alias,
  page,
  onExplore,
}: {
  node: GraphNode
  host: string
  alias: string
  page: 'map' | 'explorer'
  onExplore?: () => void
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
    <div className="space-y-2">
      <div className="flex gap-2">
        <Button size="sm" variant="primary" className="flex-1" onClick={ask}>
          <SparklesIcon className="size-3.5" /> Ask the agent
        </Button>
        <a
          href={`https://${host}${FORMS[node.type]}${node.ref}`}
          target="_blank"
          rel="noreferrer"
          title="Open in OneVizion"
          aria-label="Open in OneVizion"
          className="contents"
        >
          <Button size="sm" variant="secondary" className="aspect-square px-0">
            <ArrowTopRightOnSquareIcon className="size-3.5" />
          </Button>
        </a>
      </div>
      {explorable || page !== 'map' ? (
        <div className="flex gap-2">
          {explorable ? (
            <Button size="sm" variant="secondary" className="flex-1" onClick={explore}>
              <CodeBracketIcon className="size-3.5" /> Open in Explorer
            </Button>
          ) : null}
          {page !== 'map' ? (
            <Button size="sm" variant="secondary" className="flex-1" onClick={showOnMap}>
              <MapIcon className="size-3.5" /> Show on map
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
