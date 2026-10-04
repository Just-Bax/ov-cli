import '@xyflow/react/dist/style.css'
import dagre from '@dagrejs/dagre'
import {
  Background,
  type Edge,
  Handle,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react'
import {
  Bell,
  Bot,
  Boxes,
  ExternalLink,
  FileSpreadsheet,
  FileUp,
  GitBranch,
  type LucideIcon,
  Network,
  Package,
  RefreshCw,
  Search,
  Sparkles,
  TextCursorInput,
  X,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  GraphEdge,
  GraphNode,
  GraphNodeType,
  GraphStatus,
  InstanceGraph,
} from '@shared/types.ts'
import { useInstances } from '@/components/InstancePicker'
import { Button, Card, Chip, Page, Select, Spinner, timeAgo } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go } from '@/lib/route'

const INSTANCE_KEY = 'ov-agent.map-instance'
const EXPAND_LIMIT = 40
const NODE_W = 230
const NODE_H = 44

const TYPES: Record<
  GraphNodeType,
  { label: string; plural: string; icon: LucideIcon; color: string }
> = {
  trackor_type: { label: 'Trackor type', plural: 'Trackor types', icon: Boxes, color: '#1e88e5' },
  field: { label: 'Field', plural: 'Fields', icon: TextCursorInput, color: '#607d8b' },
  rule: { label: 'Rule', plural: 'Rules', icon: Zap, color: '#7e57c2' },
  automation: { label: 'Automation', plural: 'Automations', icon: Bot, color: '#00897b' },
  import: { label: 'Import', plural: 'Imports', icon: FileUp, color: '#ef6c00' },
  report: { label: 'Report', plural: 'Reports', icon: FileSpreadsheet, color: '#d81b60' },
  notification: { label: 'Notification', plural: 'Notifications', icon: Bell, color: '#3949ab' },
  workflow: { label: 'Workflow', plural: 'Workflows', icon: GitBranch, color: '#43a047' },
  module: { label: 'Module', plural: 'Modules', icon: Package, color: '#6d4c41' },
}

// Admin edit forms; keep in sync with FORMS in src/ov/agent/graph.py.
const FORMS: Record<GraphNodeType, string> = {
  trackor_type: '/admin/trackortypes/Form.do?id=',
  field: '/admin/configfields/Form.do?id=',
  rule: '/admin/rules/Form.do?id=',
  automation: '/admin/automation/Form.do?id=',
  import: '/admin/configimport/Form.do?id=',
  report: '/admin/reports/Form.do?id=',
  notification: '/admin/notifications/Form.do?id=',
  workflow: '/admin/wftemplate/Form.do?id=',
  module: '/admin/module/Form.do?id=',
}

const LABELS: Record<string, [string, string]> = {
  parent_of: ['Parent of', 'Child of'],
  field_of: ['Field of', 'Fields'],
  points_to: ['Points to', 'Pointed to by'],
  on: ['Acts on', 'Acted on by'],
  triggered_by: ['Triggered by', 'Triggers'],
  loads: ['Loads', 'Loaded by'],
  runs: ['Runs', 'Run by'],
  uses: ['Uses in code', 'Used in code by'],
}

interface Link {
  other: GraphNode
  kind: string
  out: boolean
  code: boolean
}

interface Index {
  byId: Map<string, GraphNode>
  links: Map<string, Link[]>
}

function index(graph: InstanceGraph): Index {
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

function degree(idx: Index, id: string): number {
  return idx.links.get(id)?.length ?? 0
}

function layout(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 18, ranksep: 90, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H })
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)
  const out = new Map<string, { x: number; y: number }>()
  for (const n of nodes) {
    const p = g.node(n.id)
    out.set(n.id, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 })
  }
  return out
}

type MapNodeData = { node: GraphNode; hidden: number; dim: boolean }

function MapNode({ data, selected }: NodeProps<Node<MapNodeData>>) {
  const meta = TYPES[data.node.type]
  const Icon = meta.icon
  return (
    <div
      className={cn(
        'flex items-center gap-2.5 rounded-full border bg-white pr-3.5 pl-1.5 shadow-[0_1px_3px_rgba(38,50,56,0.08)] transition-opacity',
        selected ? 'border-brand ring-brand/25 ring-4' : 'border-line-strong/70',
        data.node.invalid && !selected && 'border-danger/60',
        data.dim && 'opacity-35',
      )}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-1 !border-0 !bg-transparent"
      />
      <span
        className="flex size-8 shrink-0 items-center justify-center rounded-full"
        style={{ background: `${meta.color}1a`, color: meta.color }}
      >
        <Icon className="size-4" strokeWidth={1.9} />
      </span>
      <span className="min-w-0 flex-1 leading-tight">
        <span className="text-fg block truncate text-[12.5px] font-medium">{data.node.name}</span>
        <span className="text-faint block truncate text-[10.5px]">
          {meta.label}
          {data.node.invalid ? ' - invalid' : data.node.enabled === false ? ' - disabled' : ''}
        </span>
      </span>
      {data.hidden ? (
        <span className="bg-raised text-muted shrink-0 rounded-full px-1.5 text-[10.5px] font-medium">
          +{data.hidden}
        </span>
      ) : null}
      <Handle
        type="source"
        position={Position.Right}
        className="!size-1 !border-0 !bg-transparent"
      />
    </div>
  )
}

const NODE_TYPES = { map: MapNode }

function Canvas({
  idx,
  graph,
  visible,
  hiddenTypes,
  selected,
  onSelect,
  onExpand,
}: {
  idx: Index
  graph: InstanceGraph
  visible: Set<string>
  hiddenTypes: Set<GraphNodeType>
  selected?: string
  onSelect: (id?: string) => void
  onExpand: (id: string) => void
}) {
  const flow = useReactFlow()
  const shownNodes = useMemo(
    () =>
      [...visible]
        .map((id) => idx.byId.get(id))
        .filter((n): n is GraphNode => Boolean(n) && !hiddenTypes.has(n!.type)),
    [visible, hiddenTypes, idx],
  )
  const shownEdges = useMemo(() => {
    const ids = new Set(shownNodes.map((n) => n.id))
    return graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target))
  }, [shownNodes, graph])
  const positions = useMemo(() => layout(shownNodes, shownEdges), [shownNodes, shownEdges])

  const related = useMemo(() => {
    if (!selected) return undefined
    return new Set([selected, ...(idx.links.get(selected) ?? []).map((l) => l.other.id)])
  }, [selected, idx])

  const nodes: Node<MapNodeData>[] = shownNodes.map((n) => {
    const total = degree(idx, n.id)
    const onCanvas = (idx.links.get(n.id) ?? []).filter((l) => visible.has(l.other.id)).length
    return {
      id: n.id,
      type: 'map',
      position: positions.get(n.id) ?? { x: 0, y: 0 },
      selected: n.id === selected,
      data: { node: n, hidden: total - onCanvas, dim: Boolean(related && !related.has(n.id)) },
    }
  })
  const edges: Edge[] = shownEdges.map((e) => {
    const lit = selected && (e.source === selected || e.target === selected)
    return {
      id: `${e.source}>${e.target}>${e.kind}`,
      source: e.source,
      target: e.target,
      animated: Boolean(lit && e.code),
      style: {
        stroke: lit ? 'var(--color-brand)' : 'var(--color-line-strong)',
        strokeWidth: lit ? 1.8 : 1.2,
        strokeDasharray: e.code ? '4 4' : undefined,
        opacity: related && !lit ? 0.35 : 1,
      },
    }
  })

  const layoutKey = shownNodes.map((n) => n.id).join('|')
  const first = useRef(true)
  useEffect(() => {
    const timer = setTimeout(
      () => void flow.fitView({ padding: 0.2, duration: first.current ? 0 : 350, maxZoom: 1.1 }),
      30,
    )
    first.current = false
    return () => clearTimeout(timer)
  }, [layoutKey, flow])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodeClick={(_, n) => onSelect(n.id)}
      onNodeDoubleClick={(_, n) => onExpand(n.id)}
      onPaneClick={() => onSelect(undefined)}
      nodesConnectable={false}
      minZoom={0.15}
      maxZoom={1.6}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="#cfd8dc" gap={22} size={1} />
    </ReactFlow>
  )
}

function TypeDot({ type }: { type: GraphNodeType }) {
  const meta = TYPES[type]
  const Icon = meta.icon
  return (
    <span
      className="flex size-6 shrink-0 items-center justify-center rounded-full"
      style={{ background: `${meta.color}1a`, color: meta.color }}
    >
      <Icon className="size-3.5" strokeWidth={1.9} />
    </span>
  )
}

function ObjectRow({
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

function StartPoints({
  idx,
  graph,
  onFocus,
}: {
  idx: Index
  graph: InstanceGraph
  onFocus: (id: string) => void
}) {
  const top = (type: GraphNodeType, score: (n: GraphNode) => number) =>
    graph.nodes
      .filter((n) => n.type === type)
      .map((n) => ({ n, s: score(n) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 6)
  const count = (id: string, kind: string) =>
    (idx.links.get(id) ?? []).filter((l) => l.kind === kind).length
  const typesByFields = top('trackor_type', (n) => count(n.id, 'field_of'))
  const hotFields = top('field', (n) => count(n.id, 'uses') + count(n.id, 'triggered_by'))
  const invalid = graph.nodes.filter((n) => n.invalid).slice(0, 6)

  const column = (
    title: string,
    hint: string,
    rows: { n: GraphNode; s?: number }[],
    unit: string,
  ) => (
    <Card className="p-3">
      <div className="px-2 pb-2">
        <div className="text-fg text-[13px] font-semibold">{title}</div>
        <div className="text-muted text-[11.5px]">{hint}</div>
      </div>
      {rows.length ? (
        rows.map(({ n, s }) => (
          <ObjectRow
            key={n.id}
            node={n}
            hint={s ? `${s} ${unit}` : undefined}
            onClick={() => onFocus(n.id)}
          />
        ))
      ) : (
        <div className="text-faint px-2 py-2 text-[12px]">None found.</div>
      )}
    </Card>
  )

  return (
    <div className="absolute inset-0 flex items-center justify-center overflow-y-auto p-6">
      <div className="w-full max-w-[1000px]">
        <div className="text-fg text-center text-[18px] font-semibold">Pick a starting point</div>
        <div className="text-muted mt-1 mb-6 text-center text-[13px]">
          Search above, or start from what matters most on this instance. Double-click an object to
          bring in what it is linked to.
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {column('Core trackor types', 'Most fields', typesByFields, 'fields')}
          {column('Busiest fields', 'Used most by rules, imports and reports', hotFields, 'links')}
          {column(
            'Broken objects',
            'SQL or code that no longer compiles',
            invalid.map((n) => ({ n })),
            '',
          )}
        </div>
      </div>
    </div>
  )
}

function Details({
  idx,
  node,
  host,
  alias,
  visible,
  onFocus,
  onAdd,
  onExpand,
  onClose,
}: {
  idx: Index
  node: GraphNode
  host: string
  alias: string
  visible: Set<string>
  onFocus: (id: string) => void
  onAdd: (id: string) => void
  onExpand: (id: string) => void
  onClose: () => void
}) {
  const [asking, setAsking] = useState(false)
  const [open, setOpen] = useState<string>()
  const meta = TYPES[node.type]
  const links = idx.links.get(node.id) ?? []
  const groups = new Map<string, Link[]>()
  for (const l of links) {
    const [forward, back] = LABELS[l.kind] ?? [l.kind, l.kind]
    const label = l.out ? forward : back
    groups.set(label, [...(groups.get(label) ?? []), l])
  }
  const hidden = links.filter((l) => !visible.has(l.other.id)).length

  const ask = async () => {
    setAsking(true)
    try {
      const { id } = await api.startRun({
        prompt: `Explain the ${meta.label.toLowerCase()} "${node.name}" (id ${node.ref}) on ${host}: what it does, what triggers or feeds it, and what depends on it. Start with graph_query, then confirm on the instance.`,
        instance: alias,
      })
      go({ page: 'run', id })
    } finally {
      setAsking(false)
    }
  }

  return (
    <aside className="border-line-strong/60 flex w-[340px] shrink-0 flex-col border-l bg-white">
      <div className="flex items-start gap-3 px-4 pt-4 pb-3">
        <TypeDot type={node.type} />
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[14px] leading-snug font-semibold break-words">
            {node.name}
          </div>
          <div className="text-muted mt-0.5 text-[12px]">
            {meta.label} - id {node.ref}
          </div>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="text-muted hover:bg-raised hover:text-fg flex size-8 shrink-0 items-center justify-center rounded-full"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5 px-4">
        {node.trigger ? <Chip>{node.trigger}</Chip> : null}
        {node.enabled === false ? <Chip tone="warn">Disabled</Chip> : null}
        {node.invalid ? <Chip tone="danger">Invalid code</Chip> : null}
        <Chip tone="brand">{links.length} links</Chip>
      </div>
      <div className="flex flex-wrap gap-2 px-4 pt-3 pb-4">
        <Button size="sm" variant="primary" disabled={asking} onClick={() => void ask()}>
          {asking ? <Spinner className="size-3.5" /> : <Sparkles className="size-3.5" />} Ask the
          agent
        </Button>
        <a href={`https://${host}${FORMS[node.type]}${node.ref}`} target="_blank" rel="noreferrer">
          <Button size="sm" variant="ghost">
            <ExternalLink className="size-3.5" /> Open in OneVizion
          </Button>
        </a>
        {hidden ? (
          <Button size="sm" variant="secondary" onClick={() => onExpand(node.id)}>
            <Network className="size-3.5" /> Show {Math.min(hidden, EXPAND_LIMIT)} linked
          </Button>
        ) : null}
      </div>
      <div className="border-line min-h-0 flex-1 scrollbar-thin space-y-3 overflow-y-auto border-t px-3 py-3">
        {[...groups.entries()]
          .sort((a, b) => b[1].length - a[1].length)
          .map(([label, items]) => {
            const expanded = open === label
            const shown = expanded ? items : items.slice(0, 8)
            return (
              <div key={label}>
                <div className="text-faint flex items-center px-2 pb-1 text-[11.5px] font-medium">
                  <span className="flex-1">{label}</span>
                  <span>{items.length}</span>
                </div>
                {shown
                  .sort((a, b) => a.other.name.localeCompare(b.other.name))
                  .map((l) => (
                    <ObjectRow
                      key={`${label}-${l.other.id}`}
                      node={l.other}
                      hint={visible.has(l.other.id) ? 'on map' : l.code ? 'in code' : undefined}
                      onClick={() =>
                        visible.has(l.other.id) ? onFocus(l.other.id) : onAdd(l.other.id)
                      }
                    />
                  ))}
                {items.length > shown.length ? (
                  <button
                    type="button"
                    onClick={() => setOpen(label)}
                    className="text-brand-strong hover:bg-raised h-8 w-full rounded-full px-3 text-left text-[12px] font-medium"
                  >
                    Show all {items.length}
                  </button>
                ) : null}
              </div>
            )
          })}
        {!links.length ? (
          <div className="text-faint px-2 text-[12.5px]">No links found.</div>
        ) : null}
      </div>
    </aside>
  )
}

function SearchBox({ graph, onPick }: { graph: InstanceGraph; onPick: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (q.length < 2) return []
    const starts: GraphNode[] = []
    const contains: GraphNode[] = []
    for (const n of graph.nodes) {
      const name = n.name.toLowerCase()
      if (name.startsWith(q) || String(n.ref) === q) starts.push(n)
      else if (name.includes(q)) contains.push(n)
      if (starts.length > 12) break
    }
    return [...starts, ...contains].slice(0, 12)
  }, [query, graph])

  return (
    <div className="relative w-[340px]">
      <label className="border-line-strong focus-within:border-brand flex h-10 items-center gap-2 rounded-full border bg-white px-3.5 shadow-[0_2px_10px_rgba(38,50,56,0.06)]">
        <Search className="text-faint size-4 shrink-0" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search trackor types, fields, rules..."
          className="placeholder:text-faint w-full bg-transparent text-[13px] outline-none"
        />
        {query ? (
          <button type="button" onClick={() => setQuery('')} className="text-faint hover:text-fg">
            <X className="size-3.5" />
          </button>
        ) : null}
      </label>
      {results.length ? (
        <div className="border-line-strong/70 absolute top-12 right-0 left-0 z-20 rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]">
          {results.map((n) => (
            <ObjectRow
              key={n.id}
              node={n}
              hint={TYPES[n.type].label}
              onClick={() => {
                onPick(n.id)
                setQuery('')
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function TypeFilters({
  graph,
  hidden,
  onToggle,
}: {
  graph: InstanceGraph
  hidden: Set<GraphNodeType>
  onToggle: (type: GraphNodeType) => void
}) {
  const counts = useMemo(() => {
    const c = new Map<GraphNodeType, number>()
    for (const n of graph.nodes) c.set(n.type, (c.get(n.type) ?? 0) + 1)
    return c
  }, [graph])
  return (
    <div className="flex flex-wrap gap-1.5">
      {(Object.keys(TYPES) as GraphNodeType[])
        .filter((t) => counts.get(t))
        .map((t) => {
          const on = !hidden.has(t)
          return (
            <button
              key={t}
              type="button"
              onClick={() => onToggle(t)}
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-full border bg-white px-3 text-[12px] font-medium shadow-[0_1px_4px_rgba(38,50,56,0.05)] transition-colors',
                on
                  ? 'border-line-strong/70 text-text'
                  : 'text-faint border-line-strong/70 border-dashed',
              )}
            >
              <span
                className="size-2 rounded-full"
                style={{ background: on ? TYPES[t].color : 'var(--color-line-strong)' }}
              />
              {TYPES[t].plural}
              <span className="text-faint">{counts.get(t)}</span>
            </button>
          )
        })}
    </div>
  )
}

export function MapPage() {
  const { instances } = useInstances()
  const signedIn = useMemo(() => (instances ?? []).filter((i) => i.valid), [instances])
  const [alias, setAlias] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const [status, setStatus] = useState<GraphStatus>()
  const [graph, setGraph] = useState<InstanceGraph>()
  const [visible, setVisible] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string>()
  const [hiddenTypes, setHiddenTypes] = useState<Set<GraphNodeType>>(new Set())
  const [error, setError] = useState<string>()
  const idx = useMemo(() => (graph ? index(graph) : undefined), [graph])

  useEffect(() => {
    if (instances && !signedIn.some((i) => i.alias === alias)) setAlias(signedIn[0]?.alias ?? '')
  }, [instances])
  useEffect(() => {
    if (alias) localStorage.setItem(INSTANCE_KEY, alias)
  }, [alias])

  useEffect(() => {
    if (!alias) return
    let alive = true
    setGraph(undefined)
    setVisible(new Set())
    setSelected(undefined)
    setError(undefined)
    setStatus(undefined)
    api
      .graphStatus(alias)
      .then((s) => alive && setStatus(s))
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [alias])

  // Follow a build until it finishes, then load the new map without clearing the view.
  useEffect(() => {
    if (!alias || !status) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    if (status.state === 'building') {
      timer = setTimeout(() => {
        api
          .graphStatus(alias)
          .then((s) => alive && setStatus(s))
          .catch(() => undefined)
      }, 2000)
    } else if (status.builtAt && graph?.builtAt !== status.builtAt) {
      api
        .graph(alias)
        .then((g) => alive && setGraph(g))
        .catch((e: Error) => alive && setError(e.message))
    }
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [alias, status])

  const build = async () => {
    setError(undefined)
    try {
      setStatus(await api.buildGraph(alias))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const neighbors = (id: string, have: Set<string>) =>
    (idx?.links.get(id) ?? [])
      .filter((l) => !have.has(l.other.id) && !hiddenTypes.has(l.other.type))
      .sort((a, b) => degree(idx!, b.other.id) - degree(idx!, a.other.id))
      .slice(0, EXPAND_LIMIT)
      .map((l) => l.other.id)

  const focus = (id: string) => {
    setVisible(new Set([id, ...neighbors(id, new Set([id]))]))
    setSelected(id)
  }
  const expand = (id: string) => setVisible((v) => new Set([...v, id, ...neighbors(id, v)]))
  const add = (id: string) => {
    setVisible((v) => new Set([...v, id]))
    setSelected(id)
  }

  const node = selected ? idx?.byId.get(selected) : undefined
  const building = status?.state === 'building'

  const subtitle = building ? (
    <span className="text-brand-strong inline-flex items-center gap-1.5">
      <Spinner className="size-3" /> {status?.step ?? 'Building'}...
    </span>
  ) : status?.builtAt ? (
    <span>
      {status.nodes?.toLocaleString()} objects, {status.edges?.toLocaleString()} links - built{' '}
      {timeAgo(status.builtAt)}
    </span>
  ) : (
    <span>How the configuration of an instance fits together.</span>
  )

  const actions = (
    <>
      <div className="w-[260px]">
        <Select
          className="w-full"
          value={alias}
          onChange={setAlias}
          placeholder={instances ? 'No signed-in instance' : 'Loading...'}
          options={signedIn.map((i) => ({
            value: i.alias,
            label: i.tenant ? `${i.host} / ${i.tenant}` : i.host,
          }))}
        />
      </div>
      <Button variant="primary" disabled={!alias || building} onClick={() => void build()}>
        {building ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}
        {graph ? 'Refresh' : 'Build map'}
      </Button>
    </>
  )

  return (
    <Page title="Instance map" subtitle={subtitle} actions={actions}>
      <div className="flex h-full min-h-[480px]">
        <div className="bg-canvas/40 relative min-w-0 flex-1">
          {graph && idx ? (
            <>
              {visible.size ? (
                <ReactFlowProvider>
                  <Canvas
                    idx={idx}
                    graph={graph}
                    visible={visible}
                    hiddenTypes={hiddenTypes}
                    selected={selected}
                    onSelect={setSelected}
                    onExpand={expand}
                  />
                </ReactFlowProvider>
              ) : (
                <StartPoints idx={idx} graph={graph} onFocus={focus} />
              )}
              <div className="pointer-events-none absolute inset-x-4 top-4 z-10 flex flex-wrap items-start gap-3">
                <div className="pointer-events-auto">
                  <SearchBox graph={graph} onPick={focus} />
                </div>
                <div className="pointer-events-auto min-w-0 flex-1">
                  <TypeFilters
                    graph={graph}
                    hidden={hiddenTypes}
                    onToggle={(t) =>
                      setHiddenTypes((h) => {
                        const next = new Set(h)
                        if (next.has(t)) next.delete(t)
                        else next.add(t)
                        return next
                      })
                    }
                  />
                </div>
                {visible.size ? (
                  <Button
                    className="pointer-events-auto shadow-[0_1px_4px_rgba(38,50,56,0.05)]"
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setVisible(new Set())
                      setSelected(undefined)
                    }}
                  >
                    <X className="size-3.5" /> Clear
                  </Button>
                ) : null}
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center p-6">
              <Card className="w-full max-w-[460px] p-6 text-center">
                <span className="bg-brand-soft text-brand-strong mx-auto flex size-12 items-center justify-center rounded-full">
                  {building ? <Spinner className="size-5" /> : <Network className="size-5" />}
                </span>
                <div className="text-fg mt-4 text-[15px] font-semibold">
                  {building
                    ? 'Reading the configuration'
                    : status?.builtAt
                      ? 'Loading the map'
                      : 'No map yet'}
                </div>
                <div className="text-muted mt-1 text-[13px] leading-relaxed">
                  {building
                    ? `${status?.step ?? 'Starting'}. Large instances take about a minute.`
                    : status?.builtAt
                      ? 'One moment.'
                      : 'Build a map to see how trackor types, fields, rules, automations, imports, reports and workflows link together. It reads the configuration with read-only SQL and needs the Test SQL privilege.'}
                </div>
                {error || status?.error ? (
                  <div className="text-danger mt-3 text-[12.5px]">{error ?? status?.error}</div>
                ) : null}
                {!building && !status?.builtAt ? (
                  <Button
                    className="mt-5"
                    variant="primary"
                    disabled={!alias}
                    onClick={() => void build()}
                  >
                    <Network className="size-3.5" /> Build map
                  </Button>
                ) : null}
              </Card>
            </div>
          )}
        </div>
        {graph && idx && node ? (
          <Details
            idx={idx}
            node={node}
            host={graph.host}
            alias={alias}
            visible={visible}
            onFocus={setSelected}
            onAdd={add}
            onExpand={expand}
            onClose={() => setSelected(undefined)}
          />
        ) : null}
      </div>
    </Page>
  )
}
