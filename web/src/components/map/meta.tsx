import {
  Bars3BottomLeftIcon,
  BellIcon,
  BoltIcon,
  CircleStackIcon,
  CpuChipIcon,
  CubeIcon,
  DocumentArrowUpIcon,
  RectangleStackIcon,
  ShareIcon,
  TableCellsIcon,
} from '@heroicons/react/24/outline'
import type { Icon } from '@/components/ui'
import type { GraphNode, GraphNodeType, InstanceGraph } from '@shared/types.ts'

export const TYPES: Record<
  GraphNodeType,
  { label: string; plural: string; icon: Icon; color: string }
> = {
  trackor_type: {
    label: 'Trackor type',
    plural: 'Trackor types',
    icon: RectangleStackIcon,
    color: '#1e88e5',
  },
  field: { label: 'Field', plural: 'Fields', icon: Bars3BottomLeftIcon, color: '#bf8f00' },
  rule: { label: 'Rule', plural: 'Rules', icon: BoltIcon, color: '#7e57c2' },
  automation: { label: 'Automation', plural: 'Automations', icon: CpuChipIcon, color: '#00897b' },
  import: { label: 'Import', plural: 'Imports', icon: DocumentArrowUpIcon, color: '#ef6c00' },
  report: { label: 'Report', plural: 'Reports', icon: TableCellsIcon, color: '#d81b60' },
  notification: {
    label: 'Notification',
    plural: 'Notifications',
    icon: BellIcon,
    color: '#3949ab',
  },
  workflow: { label: 'Workflow', plural: 'Workflows', icon: ShareIcon, color: '#43a047' },
  module: { label: 'Module', plural: 'Modules', icon: CubeIcon, color: '#6d4c41' },
  db_package: {
    label: 'DB package',
    plural: 'DB packages',
    icon: CircleStackIcon,
    color: '#00838f',
  },
}

// Admin edit forms; keep in sync with FORMS in src/ov/agent/graph.py.
export const FORMS: Record<GraphNodeType, string> = {
  trackor_type: '/admin/trackortypes/Form.do?id=',
  field: '/admin/configfields/Form.do?id=',
  rule: '/admin/rules/Form.do?id=',
  automation: '/admin/automation/Form.do?id=',
  import: '/admin/configimport/Form.do?id=',
  report: '/admin/reports/Form.do?id=',
  notification: '/admin/notifications/Form.do?id=',
  workflow: '/admin/wftemplate/Form.do?id=',
  module: '/admin/module/Form.do?id=',
  db_package: '/admin/dbpackage/Form.do?id=',
}

export const WITH_CODE = new Set<GraphNodeType>([
  'rule',
  'db_package',
  'field',
  'import',
  'report',
  'workflow',
  'automation',
  'notification',
])

export const LABELS: Record<string, [string, string]> = {
  parent_of: ['Parent of', 'Child of'],
  field_of: ['Field of', 'Fields'],
  points_to: ['Points to', 'Pointed to by'],
  on: ['Acts on', 'Acted on by'],
  triggered_by: ['Triggered by', 'Triggers'],
  loads: ['Loads', 'Loaded by'],
  runs: ['Runs', 'Run by'],
  uses: ['Uses in code', 'Used in code by'],
  calls: ['Calls', 'Called by'],
}

export interface Link {
  other: GraphNode
  kind: string
  out: boolean
  code: boolean
}

export interface Index {
  byId: Map<string, GraphNode>
  links: Map<string, Link[]>
}

export function index(graph: InstanceGraph): Index {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const links = new Map<string, Link[]>()
  const add = (from: string, link: Link) => {
    const list = links.get(from)
    if (list) list.push(link)
    else links.set(from, [link])
  }
  for (const e of graph.edges) {
    const source = byId.get(e.source)
    const target = byId.get(e.target)
    if (!source || !target) continue
    add(source.id, { other: target, kind: e.kind, out: true, code: Boolean(e.code) })
    add(target.id, { other: source, kind: e.kind, out: false, code: Boolean(e.code) })
  }
  return { byId, links }
}

export function degree(idx: Index, id: string): number {
  return idx.links.get(id)?.length ?? 0
}

export function TypeDot({ type }: { type: GraphNodeType }) {
  const meta = TYPES[type]
  const Icon = meta.icon
  return (
    <span
      className="flex size-6 shrink-0 items-center justify-center rounded-full"
      style={{ background: `${meta.color}1a`, color: meta.color }}
    >
      <Icon className="size-3.5" />
    </span>
  )
}

export function ObjectRow({
  node,
  hint,
  onClick,
}: {
  node: GraphNode
  hint?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-raised flex h-9 w-full items-center gap-2.5 rounded-full px-2 text-left transition-colors"
    >
      <TypeDot type={node.type} />
      <span className="text-text min-w-0 flex-1 truncate text-[12.5px]">{node.name}</span>
      {hint ? <span className="text-faint shrink-0 text-[11px]">{hint}</span> : null}
    </button>
  )
}
