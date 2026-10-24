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
  ArrowUUpLeft as ArrowUturnLeftIcon,
  Check as CheckIcon,
  CaretDown as ChevronDownIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
  MapTrifold as MapIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEdge, GraphNode, GraphNodeType, InstanceGraph } from '@shared/types.ts'
import { MapSkeleton } from '@/components/common/skeletons'
import { Button, Card, Page } from '@/components/common/ui'
import { BuildingNote, GraphActions, GraphPlaceholder } from '@/components/map/MapState'
import { degree, index, type Index, ObjectRow, TYPES } from '@/components/map/meta'
import { ObjectActions } from '@/components/map/ObjectActions'
import { LinkGroups, ObjectFacts, ObjectTitle } from '@/components/map/ObjectDetails'
import { cn } from '@/lib/cn'
import { toggled } from '@/lib/collections'
import { useClickOutside } from '@/lib/hooks'
import { timeAgo } from '@/lib/time'
import { FOCUS_KEY, useInstanceGraph } from '@/lib/useInstanceGraph'

const EXPAND_LIMIT = 40
const START_POINT_ROWS = 6
const SEARCH_MIN_CHARS = 2
const SEARCH_RESULTS = 12
const TYPE_DOTS = 5

function missingPart(warning: string): string {
  return warning.split(':')[0].replace(/_/g, ' ')
}
const FIT_DELAY_MS = 30
const FIT_DURATION_MS = 350
const NODE_W = 230
const NODE_H = 44
const LAYOUT = { rankdir: 'LR', nodesep: 18, ranksep: 90, marginx: 20, marginy: 20 }
const FIT_PADDING = 0.2
const FIT_MAX_ZOOM = 1.1
const MIN_ZOOM = 0.15
const MAX_ZOOM = 1.6
const GRID_GAP_PX = 22
const GRID_COLOR = '#cfd8dc'
const EDGE_WIDTH = 1.2
const LIT_EDGE_WIDTH = 1.8
const DIM_OPACITY = 0.35

function layout(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  g.setGraph(LAYOUT)
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
        <Icon className="size-4" />
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
        strokeWidth: lit ? LIT_EDGE_WIDTH : EDGE_WIDTH,
        strokeDasharray: e.code ? '4 4' : undefined,
        opacity: related && !lit ? DIM_OPACITY : 1,
      },
    }
  })

  const layoutKey = shownNodes.map((n) => n.id).join('|')
  const first = useRef(true)

  useEffect(() => {
    const timer = setTimeout(
      () =>
        void flow.fitView({
          padding: FIT_PADDING,
          duration: first.current ? 0 : FIT_DURATION_MS,
          maxZoom: FIT_MAX_ZOOM,
        }),
      FIT_DELAY_MS,
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
      minZoom={MIN_ZOOM}
      maxZoom={MAX_ZOOM}
      proOptions={{ hideAttribution: true }}
    >
      <Background color={GRID_COLOR} gap={GRID_GAP_PX} size={1} />
    </ReactFlow>
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
      .slice(0, START_POINT_ROWS)

  const count = (id: string, kind: string) =>
    (idx.links.get(id) ?? []).filter((l) => l.kind === kind).length

  const typesByFields = top('trackor_type', (n) => count(n.id, 'field_of'))
  const hotFields = top('field', (n) => count(n.id, 'uses') + count(n.id, 'triggered_by'))
  const packages = top('db_package', (n) => (idx.links.get(n.id) ?? []).length)
  const invalid = graph.nodes.filter((n) => n.invalid).slice(0, START_POINT_ROWS)

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
            hint={s ? `${s} ${s === 1 ? unit.replace(/s$/, '') : unit}` : undefined}
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
      <div className="w-full max-w-[1240px]">
        <div className="text-fg text-center text-[18px] font-semibold">Pick a starting point</div>
        <div className="text-muted mt-1 mb-6 text-center text-[13px]">
          Search above, or start from what matters most on this instance. Double-click an object to
          bring in what it is linked to.
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {column('Core trackor types', 'Most fields', typesByFields, 'fields')}
          {column('Busiest fields', 'Used most by rules, imports and reports', hotFields, 'links')}
          {column('Shared packages', 'DB packages with the most links', packages, 'links')}
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
  const links = idx.links.get(node.id) ?? []
  const hidden = links.filter((l) => !visible.has(l.other.id)).length
  const onMap = links.length - hidden

  return (
    <aside className="border-line-strong/60 flex w-[340px] shrink-0 flex-col border-l bg-white">
      <ObjectTitle
        node={node}
        action={
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="text-muted hover:bg-raised hover:text-fg flex size-8 shrink-0 items-center justify-center rounded-full"
          >
            <XMarkIcon className="size-4" />
          </button>
        }
      />
      <ObjectFacts node={node}>
        <dt className="text-muted">Links</dt>
        <dd className="text-fg">
          {links.length}
          {onMap ? (
            <span className="text-muted">
              {onMap === links.length ? ', all on the map' : `, ${onMap} on the map`}
            </span>
          ) : null}
        </dd>
      </ObjectFacts>
      <div className="space-y-2 px-4 pt-3 pb-4">
        <ObjectActions node={node} host={host} alias={alias} page="map" />
        {hidden ? (
          <Button className="w-full" variant="ghost" onClick={() => onExpand(node.id)}>
            <MapIcon className="size-3.5" /> Show {Math.min(hidden, EXPAND_LIMIT)} more linked
          </Button>
        ) : null}
      </div>
      <div className="border-line min-h-0 flex-1 scrollbar-thin space-y-3 overflow-y-auto border-t px-3 py-3">
        <LinkGroups
          key={node.id}
          links={links}
          hint={(l) => (visible.has(l.other.id) ? 'on map' : l.code ? 'in code' : undefined)}
          onPick={(l) => (visible.has(l.other.id) ? onFocus(l.other.id) : onAdd(l.other.id))}
        />
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
    if (q.length < SEARCH_MIN_CHARS) return []

    const starts: GraphNode[] = []
    const contains: GraphNode[] = []
    for (const n of graph.nodes) {
      const name = n.name.toLowerCase()
      if (name.startsWith(q) || String(n.ref) === q) starts.push(n)
      else if (name.includes(q)) contains.push(n)
      if (starts.length > SEARCH_RESULTS) break
    }

    return [...starts, ...contains].slice(0, SEARCH_RESULTS)
  }, [query, graph])

  return (
    <div className="relative w-[320px]">
      <label className="border-line-strong focus-within:border-brand flex h-9 items-center gap-2 rounded-full border bg-white px-3.5">
        <MagnifyingGlassIcon className="text-faint size-4 shrink-0" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search trackor types, fields, rules..."
          className="placeholder:text-faint w-full bg-transparent text-[13px] outline-none"
        />
        {query ? (
          <button type="button" onClick={() => setQuery('')} className="text-faint hover:text-fg">
            <XMarkIcon className="size-3.5" />
          </button>
        ) : null}
      </label>
      {results.length ? (
        <div className="border-line-strong/70 absolute top-11 right-0 left-0 z-30 rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]">
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

function TypeMenu({
  graph,
  hidden,
  onToggle,
  onReset,
}: {
  graph: InstanceGraph
  hidden: Set<GraphNodeType>
  onToggle: (type: GraphNodeType) => void
  onReset: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const counts = useMemo(() => {
    const c = new Map<GraphNodeType, number>()
    for (const n of graph.nodes) c.set(n.type, (c.get(n.type) ?? 0) + 1)
    return c
  }, [graph])

  const types = (Object.keys(TYPES) as GraphNodeType[]).filter((t) => counts.get(t))
  const shown = types.filter((t) => !hidden.has(t)).length

  useClickOutside([ref], () => setOpen(false), open)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          'flex h-9 items-center gap-2 rounded-full border px-3.5 text-[13px] font-medium transition-colors',
          hidden.size
            ? 'border-brand/40 bg-brand-soft text-brand-strong'
            : 'border-line-strong text-text hover:bg-raised bg-white',
        )}
      >
        <span className="flex -space-x-1">
          {types.slice(0, TYPE_DOTS).map((t) => (
            <span
              key={t}
              className="size-2.5 rounded-full ring-2 ring-white"
              style={{ background: hidden.has(t) ? 'var(--color-line-strong)' : TYPES[t].color }}
            />
          ))}
        </span>
        {shown === types.length ? 'All types' : `${shown} of ${types.length} types`}
        <ChevronDownIcon
          className={cn('size-3.5 opacity-70 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open ? (
        <div className="border-line-strong/70 absolute top-11 left-0 z-30 w-[264px] rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]">
          {types.map((t) => {
            const on = !hidden.has(t)

            return (
              <button
                key={t}
                type="button"
                onClick={() => onToggle(t)}
                className="hover:bg-raised flex h-9 w-full items-center gap-2.5 rounded-full px-2.5 transition-colors"
              >
                <span
                  className="flex size-4.5 shrink-0 items-center justify-center rounded-full border-2"
                  style={{
                    borderColor: on ? TYPES[t].color : 'var(--color-line-strong)',
                    background: on ? TYPES[t].color : 'white',
                  }}
                >
                  {on ? <CheckIcon className="size-3 text-white" /> : null}
                </span>
                <span className={cn('flex-1 text-left text-[13px]', on ? 'text-fg' : 'text-faint')}>
                  {TYPES[t].plural}
                </span>
                <span className="text-faint text-[12px]">{counts.get(t)?.toLocaleString()}</span>
              </button>
            )
          })}
          {hidden.size ? (
            <button
              type="button"
              onClick={onReset}
              className="text-brand-strong hover:bg-raised mt-1 h-9 w-full rounded-full text-[12.5px] font-medium"
            >
              Show all types
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function MapPage() {
  const state = useInstanceGraph()
  const { alias, label, status, graph, building } = state
  const [visible, setVisible] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string>()
  const [hiddenTypes, setHiddenTypes] = useState<Set<GraphNodeType>>(new Set())
  const idx = useMemo(() => (graph ? index(graph) : undefined), [graph])
  const node = selected ? idx?.byId.get(selected) : undefined

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

  const clear = () => {
    setVisible(new Set())
    setSelected(undefined)
  }

  useEffect(clear, [alias])

  useEffect(() => {
    const requestedFocus = localStorage.getItem(FOCUS_KEY)
    if (!idx || !requestedFocus || !idx.byId.has(requestedFocus)) return
    localStorage.removeItem(FOCUS_KEY)
    focus(requestedFocus)
  }, [idx])

  const subtitle = building ? (
    <BuildingNote step={status?.step} />
  ) : status?.builtAt ? (
    <span>
      {label ? `${label} - ` : ''}
      {status.nodes?.toLocaleString()} objects, {status.edges?.toLocaleString()} links - built{' '}
      {timeAgo(status.builtAt)}
      {status.source === 'export' ? ' from component exports' : ''}
      {graph?.warnings.length ? (
        <span className="text-warn cursor-help" title={graph.warnings.join('\n\n')}>
          {' '}
          - Missing: {graph.warnings.map(missingPart).join(', ')}
        </span>
      ) : null}
    </span>
  ) : (
    <span>How the configuration of an instance fits together.</span>
  )

  return (
    <Page title="Instance map" subtitle={subtitle} actions={<GraphActions state={state} />}>
      <div className="flex h-full min-h-[480px]">
        <div className="bg-canvas/40 flex min-w-0 flex-1 flex-col">
          {graph && idx ? (
            <>
              <div className="border-line flex h-14 shrink-0 items-center gap-2 border-b bg-white px-4">
                <SearchBox graph={graph} onPick={focus} />
                <TypeMenu
                  graph={graph}
                  hidden={hiddenTypes}
                  onToggle={(type) => setHiddenTypes((h) => toggled(h, type))}
                  onReset={() => setHiddenTypes(new Set())}
                />
                <div className="flex-1" />
                {visible.size ? (
                  <span className="text-muted text-[12.5px]">{visible.size} on the map</span>
                ) : null}
                <Button variant="secondary" disabled={!visible.size} onClick={clear}>
                  <ArrowUturnLeftIcon className="size-3.5" /> Clear map
                </Button>
              </div>
              <div className="relative min-h-0 flex-1">
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
              </div>
            </>
          ) : (
            <GraphPlaceholder state={state} skeleton={<MapSkeleton />} />
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
