import {
  CaretRight as ChevronRightIcon,
  Code as CodeBracketIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type {
  CodeHint,
  CodeSection,
  GraphNode,
  GraphNodeType,
  InstanceGraph,
  ObjectActivity,
} from '@shared/types.ts'
import { CodeSkeleton, ExplorerSkeleton } from '@/components/common/skeletons'
import { Card, EmptyState, Page, SkeletonText } from '@/components/common/ui'
import { CodeView } from '@/components/explorer/CodeView'
import { BuildingNote, GraphActions, GraphPlaceholder } from '@/components/map/MapState'
import {
  degree,
  fieldsOf,
  index,
  type Index,
  ObjectRow,
  statusOf,
  TypeDot,
  TYPES,
  WITH_CODE,
} from '@/components/map/meta'
import { ObjectActions } from '@/components/map/ObjectActions'
import { LinkGroups, ObjectFacts, ObjectTitle } from '@/components/map/ObjectDetails'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { groupBy, toggled } from '@/lib/collections'
import { openDraft } from '@/lib/draft'
import { refIndex } from '@/lib/references'
import { timeAgo } from '@/lib/time'
import { EXPLORE_KEY, useInstanceGraph } from '@/lib/useInstanceGraph'

const TREE_ORDER: GraphNodeType[] = [
  'rule',
  'db_package',
  'trackor_type',
  'automation',
  'import',
  'report',
  'notification',
  'workflow',
  'module',
]
const WITH_ACTIVITY = new Set<GraphNodeType>(['rule', 'import', 'report', 'module', 'automation'])
const GROUP_LIMIT = 300
const FIELD_ROWS = 200
const TREE_INDENT = 14
const FAILED_RUN_STATUS = /error|exception|interrupt/i
const ITEM_PAD_PX = 12
const GROUP_PAD_PX = 6
const MORE_PAD_PX = 26

type Loaded<T> =
  { state: 'loading' } | { state: 'ready'; value: T } | { state: 'error'; error: string }

type SetLoaded<T> = Dispatch<SetStateAction<Record<string, Loaded<T>>>>

function TreeItem({
  node,
  active,
  depth,
  onOpen,
}: {
  node: GraphNode
  active: boolean
  depth: number
  onOpen: (id: string) => void
}) {
  const status = statusOf(node)

  return (
    <button
      type="button"
      onClick={() => onOpen(node.id)}
      style={{ paddingLeft: ITEM_PAD_PX + depth * TREE_INDENT }}
      className={cn(
        'flex h-8 w-full items-center gap-2 rounded-full pr-3 text-left text-[12.5px] transition-colors',
        active ? 'bg-brand-soft text-brand-strong font-medium' : 'text-text hover:bg-raised',
        node.enabled === false && !active && 'text-faint',
      )}
    >
      <span
        className={cn(
          'size-1.5 shrink-0 rounded-full',
          node.invalid
            ? 'bg-danger'
            : status?.dot === 'bg-warn'
              ? 'bg-line-strong'
              : 'bg-transparent',
        )}
      />
      <span className="min-w-0 flex-1 truncate">{node.name}</span>
    </button>
  )
}

function GroupHeader({
  open,
  onToggle,
  label,
  count,
  depth,
  type,
}: {
  open: boolean
  onToggle: () => void
  label: string
  count: number
  depth: number
  type?: GraphNodeType
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{ paddingLeft: GROUP_PAD_PX + depth * TREE_INDENT }}
      className="text-text hover:bg-raised flex h-8 w-full items-center gap-2 rounded-full pr-3 text-left text-[12.5px] font-medium transition-colors"
    >
      <ChevronRightIcon
        className={cn('text-faint size-3.5 shrink-0 transition-transform', open && 'rotate-90')}
      />
      {type ? <TypeDot type={type} /> : null}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="text-faint text-[11.5px] font-normal">{count.toLocaleString()}</span>
    </button>
  )
}

function Tree({
  graph,
  idx,
  active,
  onOpen,
}: {
  graph: InstanceGraph
  idx: Index
  active?: string
  onOpen: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set(['rule']))
  const toggle = (key: string) => setOpen((o) => toggled(o, key))

  const byType = useMemo(() => {
    const groups = groupBy(graph.nodes, (n) => n.type)
    for (const list of groups.values()) list.sort((a, b) => a.name.localeCompare(b.name))
    return groups
  }, [graph])

  const q = query.trim().toLowerCase()
  const matches = (n: GraphNode) => !q || n.name.toLowerCase().includes(q) || String(n.ref) === q

  const list = (nodes: GraphNode[], depth: number) => (
    <>
      {nodes.slice(0, GROUP_LIMIT).map((n) => (
        <TreeItem key={n.id} node={n} active={n.id === active} depth={depth} onOpen={onOpen} />
      ))}
      {nodes.length > GROUP_LIMIT ? (
        <div
          className="text-faint py-1 text-[11.5px]"
          style={{ paddingLeft: MORE_PAD_PX + depth * TREE_INDENT }}
        >
          {nodes.length - GROUP_LIMIT} more; filter to narrow down
        </div>
      ) : null}
    </>
  )

  return (
    <aside className="border-line-strong/60 flex w-[300px] shrink-0 flex-col border-r bg-white">
      <div className="p-3">
        <label className="border-line-strong focus-within:border-brand flex h-9 items-center gap-2 rounded-full border bg-white px-3.5">
          <MagnifyingGlassIcon className="text-faint size-3.5 shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter objects"
            className="placeholder:text-faint w-full bg-transparent text-[12.5px] outline-none"
          />
          {query ? (
            <button type="button" onClick={() => setQuery('')} className="text-faint hover:text-fg">
              <XMarkIcon className="size-3.5" />
            </button>
          ) : null}
        </label>
      </div>
      <div className="min-h-0 flex-1 scrollbar-thin space-y-0.5 overflow-y-auto px-2 pb-3">
        {TREE_ORDER.filter((t) => byType.get(t)?.length).map((type) => {
          const all = byType.get(type) ?? []
          const shown = all.filter(matches)
          if (q && !shown.length) return null

          const isOpen = Boolean(q) || open.has(type)

          return (
            <div key={type}>
              <GroupHeader
                open={isOpen}
                onToggle={() => toggle(type)}
                label={TYPES[type].plural}
                count={q ? shown.length : all.length}
                depth={0}
                type={type}
              />
              {!isOpen
                ? null
                : type === 'rule'
                  ? bySize(groupBy(shown, (n) => n.trigger || 'Other')).map(([trigger, rules]) => {
                      const key = `rule:${trigger}`
                      const subOpen = Boolean(q) || open.has(key)

                      return (
                        <div key={key}>
                          <GroupHeader
                            open={subOpen}
                            onToggle={() => toggle(key)}
                            label={trigger}
                            count={rules.length}
                            depth={1}
                          />
                          {subOpen ? list(rules, 2) : null}
                        </div>
                      )
                    })
                  : type === 'trackor_type'
                    ? shown.slice(0, GROUP_LIMIT).map((tt) => {
                        const key = `tt:${tt.id}`
                        const fields = fieldsOf(idx, tt.id).sort((a, b) =>
                          a.name.localeCompare(b.name),
                        )
                        const ttOpen = open.has(key)

                        return (
                          <div key={key}>
                            <div className="flex items-center">
                              <button
                                type="button"
                                aria-label={ttOpen ? 'Collapse' : 'Expand'}
                                onClick={() => toggle(key)}
                                className="text-faint hover:text-fg flex size-6 shrink-0 items-center justify-center rounded-full"
                                style={{ marginLeft: GROUP_PAD_PX + TREE_INDENT }}
                              >
                                <ChevronRightIcon
                                  className={cn(
                                    'size-3.5 transition-transform',
                                    ttOpen && 'rotate-90',
                                  )}
                                />
                              </button>
                              <div className="min-w-0 flex-1">
                                <TreeItem
                                  node={tt}
                                  active={tt.id === active}
                                  depth={0}
                                  onOpen={onOpen}
                                />
                              </div>
                            </div>
                            {ttOpen ? list(fields, 3) : null}
                          </div>
                        )
                      })
                    : list(shown, 1)}
            </div>
          )
        })}
      </div>
    </aside>
  )
}

function bySize<T>(groups: Map<string, T[]>): [string, T[]][] {
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length)
}

const SEVERITY_DOT: Record<CodeHint['severity'], string> = {
  error: 'bg-danger',
  warn: 'bg-warn',
  info: 'bg-brand',
}

function Inspector({
  node,
  idx,
  host,
  alias,
  sections,
  activity,
  onOpen,
  onReveal,
}: {
  node: GraphNode
  idx: Index
  host: string
  alias: string
  sections?: Loaded<CodeSection[]>
  activity?: Loaded<ObjectActivity[]>
  onOpen: (id: string) => void
  onReveal: (section: number, line: number) => void
}) {
  const meta = TYPES[node.type]
  const links = idx.links.get(node.id) ?? []
  const reviewable =
    WITH_CODE.has(node.type) && !(sections?.state === 'ready' && !sections.value.length)
  const hints =
    sections?.state === 'ready'
      ? sections.value.flatMap((s, i) => s.hints.map((h) => ({ ...h, section: i })))
      : []

  const subject = `the ${meta.label.toLowerCase()} "${node.name}" (id ${node.ref}) on ${host}`
  const review = () =>
    openDraft({
      instance: alias,
      prompt:
        `Review ${subject} for performance and correctness. Read its full code, use ov_map to see what triggers it and what it touches, and check its recent errors. Then propose concrete fixes as change cards with the complete current code as before.` +
        (hints.length
          ? ` Static checks already flagged: ${hints.map((h) => `line ${h.line} ${h.title}`).join('; ')}.`
          : ''),
    })

  return (
    <aside className="border-line-strong/60 flex w-[340px] shrink-0 flex-col border-l bg-white">
      <ObjectTitle node={node} />
      <ObjectFacts node={node}>
        {node.type === 'rule' ? (
          <>
            <dt className="text-muted">Runs</dt>
            <dd className="text-fg">
              {node.async ? 'Async, in the background' : 'Sync, while the user waits'}
            </dd>
          </>
        ) : null}
        <dt className="text-muted">Links</dt>
        <dd className="text-fg">{links.length.toLocaleString()}</dd>
      </ObjectFacts>
      <div className="px-4 pt-3 pb-4">
        <ObjectActions
          node={node}
          host={host}
          alias={alias}
          page="explorer"
          onReview={reviewable ? review : undefined}
        />
      </div>

      <div className="border-line min-h-0 flex-1 scrollbar-thin space-y-4 overflow-y-auto border-t px-3 py-3">
        {reviewable ? (
          <section>
            <div className="text-faint flex items-center px-2 pb-1 text-[11.5px] font-medium">
              <span className="flex-1">Hints</span>
              {hints.length ? <span>{hints.length}</span> : null}
            </div>
            {!sections || sections.state === 'loading' ? (
              <div className="px-2 py-1">
                <SkeletonText lines={2} />
              </div>
            ) : sections.state === 'error' ? (
              <div className="text-faint px-2 text-[12px]">Could not read the code.</div>
            ) : hints.length ? (
              <div className="space-y-1">
                {hints.map((h, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => onReveal(h.section, h.line)}
                    className="hover:bg-raised flex w-full items-start gap-2.5 rounded-2xl px-2.5 py-2 text-left transition-colors"
                  >
                    <span
                      className={cn(
                        'mt-1.5 size-2 shrink-0 rounded-full',
                        SEVERITY_DOT[h.severity],
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="text-fg flex items-center gap-2 text-[12.5px] font-medium">
                        <span className="min-w-0 flex-1">{h.title}</span>
                        <span className="text-faint shrink-0 text-[11px] font-normal">
                          line {h.line}
                        </span>
                      </span>
                      <span className="text-muted mt-0.5 block text-[11.5px] leading-relaxed">
                        {h.detail}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-ok px-2 text-[12px]">No issues found by the quick checks.</div>
            )}
          </section>
        ) : null}

        {WITH_ACTIVITY.has(node.type) ? (
          <section>
            <div className="text-faint px-2 pb-1 text-[11.5px] font-medium">Recent runs</div>
            {!activity || activity.state === 'loading' ? (
              <div className="px-2 py-1">
                <SkeletonText lines={2} />
              </div>
            ) : activity.state === 'error' ? (
              <div className="text-faint px-2 text-[12px]">{activity.error}</div>
            ) : activity.value.length ? (
              <div className="space-y-1">
                {activity.value.map((a, i) => {
                  const failed = FAILED_RUN_STATUS.test(a.status ?? '')

                  return (
                    <div key={i} className="rounded-2xl px-2.5 py-1.5">
                      <div className="flex items-center gap-2 text-[12px]">
                        <span
                          className={cn(
                            'size-2 shrink-0 rounded-full',
                            failed ? 'bg-danger' : 'bg-ok',
                          )}
                        />
                        <span className="text-fg min-w-0 flex-1 truncate">{a.status}</span>
                        <span className="text-faint shrink-0 text-[11px]">
                          {a.ts ? timeAgo(a.ts.replace(' ', 'T')) : ''}
                          {a.runtime ? ` - ${a.runtime}s` : ''}
                        </span>
                      </div>
                      {a.message ? (
                        <div className="text-muted mt-0.5 line-clamp-3 pl-4 text-[11.5px] leading-relaxed">
                          {a.message}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="text-faint px-2 text-[12px]">No recorded runs.</div>
            )}
          </section>
        ) : null}

        <LinkGroups
          links={links}
          hint={(l) => (l.code ? 'in code' : undefined)}
          onPick={(l) => onOpen(l.other.id)}
        />
      </div>
    </aside>
  )
}

function Tabs({
  tabs,
  active,
  idx,
  onSelect,
  onClose,
}: {
  tabs: string[]
  active?: string
  idx: Index
  onSelect: (id: string) => void
  onClose: (id: string) => void
}) {
  return (
    <div className="border-line flex h-12 shrink-0 [scrollbar-width:none] items-center gap-1.5 overflow-x-auto border-b bg-white px-3">
      {tabs.map((id) => {
        const node = idx.byId.get(id)
        if (!node) return null

        const on = id === active
        const Icon = TYPES[node.type].icon

        return (
          <div
            key={id}
            className={cn(
              'group/tab flex h-8 max-w-[240px] shrink-0 items-center gap-2 rounded-full pr-1 pl-1.5 text-[12.5px] transition-colors',
              on ? 'bg-brand-soft text-brand-strong font-medium' : 'text-text hover:bg-raised',
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(id)}
              className="flex min-w-0 items-center gap-2"
            >
              <span
                className="flex size-5 shrink-0 items-center justify-center rounded-full"
                style={{ background: `${TYPES[node.type].color}1a`, color: TYPES[node.type].color }}
              >
                <Icon className="size-3" />
              </span>
              <span className="truncate">{node.name}</span>
            </button>
            <button
              type="button"
              aria-label="Close tab"
              onClick={() => onClose(id)}
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full hover:bg-black/[0.06]',
                on ? 'opacity-100' : 'opacity-0 group-hover/tab:opacity-100',
              )}
            >
              <XMarkIcon className="size-3" />
            </button>
          </div>
        )
      })}
    </div>
  )
}

function NoCode({
  node,
  idx,
  onOpen,
}: {
  node: GraphNode
  idx: Index
  onOpen: (id: string) => void
}) {
  const fields = fieldsOf(idx, node.id).sort((a, b) => degree(idx, b.id) - degree(idx, a.id))

  return (
    <div className="h-full overflow-y-auto p-6">
      <Card className="mx-auto max-w-[720px] p-5">
        <div className="flex items-center gap-3">
          <TypeDot type={node.type} />
          <div>
            <div className="text-fg text-[14px] font-semibold">{node.name}</div>
            <div className="text-muted text-[12px]">
              {node.type === 'trackor_type'
                ? `${fields.length.toLocaleString()} fields, most used in code first`
                : `${TYPES[node.type].label} without code. Its links are on the right.`}
            </div>
          </div>
        </div>
        {fields.length ? (
          <div className="mt-4 grid gap-x-2 sm:grid-cols-2">
            {fields.slice(0, FIELD_ROWS).map((f) => (
              <ObjectRow
                key={f.id}
                node={f}
                hint={degree(idx, f.id) > 1 ? `${degree(idx, f.id) - 1} links` : undefined}
                onClick={() => onOpen(f.id)}
              />
            ))}
          </div>
        ) : null}
      </Card>
    </div>
  )
}

export function ExplorerPage() {
  const state = useInstanceGraph()
  const { alias, label, status, graph, building } = state
  const idx = useMemo(() => (graph ? index(graph) : undefined), [graph])
  const [tabs, setTabs] = useState<string[]>([])
  const [active, setActive] = useState<string>()
  const [code, setCode] = useState<Record<string, Loaded<CodeSection[]>>>({})
  const [activity, setActivity] = useState<Record<string, Loaded<ObjectActivity[]>>>({})
  const [sectionOf, setSectionOf] = useState<Record<string, number>>({})
  const [reveal, setReveal] = useState<{ line: number; at: number }>()
  const currentAlias = useRef(alias)
  currentAlias.current = alias
  const node = active ? idx?.byId.get(active) : undefined

  useEffect(() => {
    setTabs([])
    setActive(undefined)
    setCode({})
    setActivity({})
  }, [alias, graph?.builtAt])

  const open = useCallback((id: string) => {
    setTabs((t) => (t.includes(id) ? t : [...t, id]))
    setActive(id)
  }, [])

  const close = (id: string) => {
    setTabs((t) => {
      const next = t.filter((x) => x !== id)
      if (active === id) setActive(next.at(-1))
      return next
    })
  }

  useEffect(() => {
    const requested = localStorage.getItem(EXPLORE_KEY)
    if (!idx || !requested || !idx.byId.has(requested)) return
    localStorage.removeItem(EXPLORE_KEY)
    open(requested)
  }, [idx])

  useEffect(() => {
    if (!node || !alias) return

    const track = <T,>(set: SetLoaded<T>, load: () => Promise<T>) => {
      const settle = (next: Loaded<T>) =>
        currentAlias.current === alias && set((all) => ({ ...all, [node.id]: next }))

      settle({ state: 'loading' })

      load().then(
        (value) => settle({ state: 'ready', value }),
        (e: Error) => settle({ state: 'error', error: e.message }),
      )
    }

    if (WITH_CODE.has(node.type) && !code[node.id])
      track(setCode, () => api.source(alias, node.id).then((r) => r.sections))

    if (WITH_ACTIVITY.has(node.type) && !activity[node.id])
      track(setActivity, () => api.activity(alias, node.id))
  }, [node?.id, alias])

  const refs = useMemo(() => refIndex(graph?.nodes ?? [], idx), [graph, idx])
  const facts = useCallback(
    (n: GraphNode) => {
      const links = idx?.links.get(n.id) ?? []
      const count = (kind: string, out: boolean) =>
        links.filter((l) => l.kind === kind && l.out === out).length

      const owner = links.find((l) => l.kind === 'field_of' && l.out)?.other
      const usedBy = count('uses', false)
      const calledBy = count('calls', false)
      const fields = count('field_of', false)

      return [
        owner ? `Field of ${owner.name}` : '',
        fields ? `${fields.toLocaleString()} fields` : '',
        usedBy ? `Used in code by ${usedBy.toLocaleString()}` : '',
        calledBy ? `Called by ${calledBy.toLocaleString()}` : '',
        n.enabled === false ? 'Disabled' : '',
        n.invalid ? 'Invalid code' : '',
      ].filter(Boolean)
    },
    [idx],
  )

  const sections = node ? code[node.id] : undefined
  const section = node ? (sectionOf[node.id] ?? 0) : 0
  const current = sections?.state === 'ready' ? sections.value[section] : undefined

  const subtitle = building ? (
    <BuildingNote step={status?.step} />
  ) : graph ? (
    <span>
      Code and configuration of {label || graph.host} - map built {timeAgo(graph.builtAt)}
    </span>
  ) : (
    <span>Browse rules, packages and configuration with their code.</span>
  )

  return (
    <Page title="Code explorer" subtitle={subtitle} actions={<GraphActions state={state} />}>
      {graph && idx ? (
        <div className="flex h-full min-h-[480px]">
          <Tree graph={graph} idx={idx} active={active} onOpen={open} />
          <div className="flex min-w-0 flex-1 flex-col bg-white">
            {tabs.length ? (
              <Tabs tabs={tabs} active={active} idx={idx} onSelect={setActive} onClose={close} />
            ) : null}
            {node && sections?.state === 'ready' && sections.value.length > 1 ? (
              <div className="border-line flex h-11 shrink-0 [scrollbar-width:none] items-center gap-1.5 overflow-x-auto border-b px-3">
                {sections.value.map((s, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setSectionOf((m) => ({ ...m, [node.id]: i }))}
                    className={cn(
                      'h-7 shrink-0 rounded-full px-3 text-[12px] font-medium transition-colors',
                      i === section ? 'bg-fg text-white' : 'text-muted hover:bg-raised',
                    )}
                  >
                    {s.title}
                    {s.hints.length ? (
                      <span
                        className={cn('ml-1.5', i === section ? 'text-white/70' : 'text-faint')}
                      >
                        {s.hints.length}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            ) : null}
            <div className="relative min-h-0 flex-1">
              {!node ? (
                <div className="flex h-full items-center justify-center p-6">
                  <EmptyState icon={CodeBracketIcon} title="Open something">
                    Pick a rule, package or trackor type on the left. References in the code are
                    links: hover one for details, click it to open.
                  </EmptyState>
                </div>
              ) : !WITH_CODE.has(node.type) ? (
                <NoCode node={node} idx={idx} onOpen={open} />
              ) : !sections || sections.state === 'loading' ? (
                <CodeSkeleton />
              ) : sections.state === 'error' ? (
                <div className="text-danger p-6 text-[13px]">{sections.error}</div>
              ) : current ? (
                <CodeView
                  code={current.code}
                  hints={current.hints}
                  refs={refs}
                  facts={facts}
                  onOpen={(n) => open(n.id)}
                  instanceHost={label}
                  alias={alias}
                  revealLine={reveal}
                />
              ) : (
                <NoCode node={node} idx={idx} onOpen={open} />
              )}
            </div>
          </div>
          {node ? (
            <Inspector
              key={node.id}
              node={node}
              idx={idx}
              host={graph.host}
              alias={alias}
              sections={sections}
              activity={activity[node.id]}
              onOpen={open}
              onReveal={(s, line) => {
                setSectionOf((m) => ({ ...m, [node.id]: s }))
                setReveal({ line, at: Date.now() })
              }}
            />
          ) : null}
        </div>
      ) : (
        <GraphPlaceholder state={state} skeleton={<ExplorerSkeleton />} />
      )}
    </Page>
  )
}
