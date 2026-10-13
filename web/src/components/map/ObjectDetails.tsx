import { type ReactNode, useState } from 'react'
import type { GraphNode } from '@shared/types.ts'
import { type Link, linkGroups, ObjectRow, statusOf, TypeDot, TYPES } from '@/components/map/meta'
import { cn } from '@/lib/cn'

const GROUP_PREVIEW_ROWS = 8

export function ObjectTitle({ node, action }: { node: GraphNode; action?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 px-4 pt-4 pb-3">
      <TypeDot type={node.type} />
      <div className="min-w-0 flex-1">
        <div className="text-fg text-[14px] leading-snug font-semibold break-words">
          {node.name}
        </div>
        <div className="text-muted mt-0.5 text-[12px]">
          {TYPES[node.type].label} - id {node.ref}
        </div>
      </div>
      {action}
    </div>
  )
}

export function ObjectFacts({ node, children }: { node: GraphNode; children: ReactNode }) {
  const status = statusOf(node)

  return (
    <dl className="bg-raised mx-4 grid grid-cols-[72px_1fr] gap-x-3 gap-y-2 rounded-2xl px-4 py-3 text-[12.5px]">
      {status ? (
        <>
          <dt className="text-muted">Status</dt>
          <dd className="text-fg flex items-center gap-2 font-medium">
            <span className={cn('size-2 rounded-full', status.dot)} />
            {status.label}
          </dd>
        </>
      ) : null}
      {node.trigger ? (
        <>
          <dt className="text-muted">Trigger</dt>
          <dd className="text-fg">{node.trigger}</dd>
        </>
      ) : null}
      {children}
    </dl>
  )
}

export function LinkGroups({
  links,
  hint,
  onPick,
}: {
  links: Link[]
  hint: (link: Link) => string | undefined
  onPick: (link: Link) => void
}) {
  const [expanded, setExpanded] = useState<string>()

  return linkGroups(links).map(([label, items]) => {
    const shown = expanded === label ? items : items.slice(0, GROUP_PREVIEW_ROWS)

    return (
      <section key={label}>
        <div className="text-faint flex items-center px-2 pb-1 text-[11.5px] font-medium">
          <span className="flex-1">{label}</span>
          <span>{items.length}</span>
        </div>
        {[...shown]
          .sort((a, b) => a.other.name.localeCompare(b.other.name))
          .map((l) => (
            <ObjectRow
              key={`${label}-${l.other.id}`}
              node={l.other}
              hint={hint(l)}
              onClick={() => onPick(l)}
            />
          ))}
        {items.length > shown.length ? (
          <button
            type="button"
            onClick={() => setExpanded(label)}
            className="text-brand-strong hover:bg-raised h-8 w-full rounded-full px-3 text-left text-[12px] font-medium"
          >
            Show all {items.length}
          </button>
        ) : null}
      </section>
    )
  })
}
