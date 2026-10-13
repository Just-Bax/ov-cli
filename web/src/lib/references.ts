import type { GraphNode, GraphNodeType } from '@shared/types.ts'
import type { Index } from '@/components/map/meta'

type RefKind = 'objref' | 'name' | 'id' | 'call'
export type Ref = { start: number; end: number; node: GraphNode; kind: RefKind; text: string }
export type RefIndex = {
  objrefs: Map<string, GraphNode>
  names: Map<string, GraphNode>
  byRef: Map<number, GraphNode[]>
  packages: Map<string, GraphNode>
}

const OBJREF = /\bid\.[A-Za-z0-9_.]+/gi
const QUOTED = /(['"])([A-Za-z][A-Za-z0-9_$#]{2,})\1/g
const NUMBER = /\b\d{6,12}\b/g
const CALL = /\b([A-Za-z][A-Za-z0-9_$#]*)(?=\s*\.\s*[A-Za-z])/g
const OBJREF_KINDS: Record<string, GraphNodeType> = { imp: 'import', rpt: 'report', wf: 'workflow' }
const NAMED: GraphNodeType[] = ['field', 'trackor_type', 'db_package']

const ID_COLUMNS: [string, GraphNodeType][] = [
  ['config_field_id', 'field'],
  ['field_id', 'field'],
  ['cf_id', 'field'],
  ['xitor_type_id', 'trackor_type'],
  ['trackor_type_id', 'trackor_type'],
  ['parent_type_id', 'trackor_type'],
  ['child_type_id', 'trackor_type'],
  ['rule_id', 'rule'],
  ['imp_spec_id', 'import'],
  ['report_file_id', 'report'],
  ['autom_id', 'automation'],
  ['notif_id', 'notification'],
  ['wf_template_id', 'workflow'],
  ['module_id', 'module'],
  ['db_package_id', 'db_package'],
]
const ID_KEYWORDS = new Set(
  (
    'and or not in is null then when where else case return values default set select from on ' +
    'between like constant number integer pls_integer varchar2 varchar char date type rowtype ' +
    'if elsif loop'
  ).split(' '),
)
const IDENT = /:?[A-Za-z_][A-Za-z0-9_$#]*/g
const NAME_COMMENT = /^\s*(?:\/\*\s*([^*]+?)\s*\*\/|--\s*(\S+))/

function idKind(before: string): GraphNodeType | undefined {
  const text = (before.split(/[;\n]/).at(-1) ?? '')
    .replace(/'[^']*'/g, "''")
    .replace(/\/\*.*?\*\//g, ' ')

  let depth = 0
  for (let i = text.length - 1; i >= 0; i--) {
    if (text[i] === ')') depth++
    else if (text[i] === '(') {
      if (depth === 0) {
        const call = /([A-Za-z_][A-Za-z0-9_$#]*)\s*$/.exec(text.slice(0, i))
        if (call && call[1].toLowerCase().endsWith('byid')) return 'field'
        break
      }
      depth--
    }
  }

  for (const token of [...text.matchAll(IDENT)].map((m) => m[0].toLowerCase()).reverse()) {
    if (ID_KEYWORDS.has(token)) continue
    if (token.startsWith(':')) return undefined
    return ID_COLUMNS.find(([column]) => token.endsWith(column))?.[1]
  }

  return undefined
}

function byId(index: RefIndex, number: string, before: string, after: string) {
  const candidates = index.byRef.get(Number(number)) ?? []
  const kind = idKind(before)
  if (kind) return candidates.find((n) => n.type === kind)

  const m = NAME_COMMENT.exec(after)
  const name = m ? (m[1] ?? m[2]).toLowerCase() : undefined
  return name ? candidates.find((n) => n.name.toLowerCase() === name) : undefined
}

const objrefSegment = (name: string) => name.toLowerCase().replace(/ /g, '_')

function unique<K>(entries: [K, GraphNode][]): Map<K, GraphNode> {
  const out = new Map<K, GraphNode>()
  const taken = new Set<K>()
  for (const [k, node] of entries) {
    if (out.has(k)) taken.add(k)
    else out.set(k, node)
  }

  for (const k of taken) out.delete(k)
  return out
}

export function refIndex(nodes: GraphNode[], idx?: Index): RefIndex {
  const objrefs = new Map<string, GraphNode>()
  for (const n of nodes) {
    if (n.type === 'trackor_type') objrefs.set(`id.${objrefSegment(n.name)}.tt`, n)
    else if (n.type === 'field') {
      const owner = idx?.links.get(n.id)?.find((l) => l.kind === 'field_of' && l.out)?.other
      if (owner) objrefs.set(`id.${objrefSegment(owner.name)}.cf.${objrefSegment(n.name)}`, n)
    } else {
      const prefix = Object.entries(OBJREF_KINDS).find(([, t]) => t === n.type)?.[0]
      if (prefix) objrefs.set(`id.${prefix}.${objrefSegment(n.name)}`, n)
    }
  }

  return {
    objrefs,
    names: unique(
      nodes
        .filter((n) => NAMED.includes(n.type) && n.name.length > 3)
        .map((n) => [n.name.toUpperCase(), n]),
    ),
    byRef: nodes.reduce((m, n) => m.set(n.ref, [...(m.get(n.ref) ?? []), n]), new Map()),
    packages: new Map(
      nodes.filter((n) => n.type === 'db_package').map((n) => [n.name.toUpperCase(), n]),
    ),
  }
}

function objref(text: string, index: RefIndex): GraphNode | undefined {
  const parts = text.toLowerCase().split('.').slice(1).filter(Boolean)
  if (parts.length >= 3 && parts[1] === 'cf')
    return index.objrefs.get(`id.${parts[0]}.cf.${parts[2]}`)
  if (parts.length >= 2 && parts[0] in OBJREF_KINDS)
    return index.objrefs.get(`id.${parts[0]}.${parts[1]}`)
  return parts.length ? index.objrefs.get(`id.${parts[0]}.tt`) : undefined
}

export function findRefs(line: string, index: RefIndex): Ref[] {
  const found: Ref[] = []
  const free = (start: number, end: number) => found.every((r) => end <= r.start || start >= r.end)
  const add = (start: number, text: string, node: GraphNode | undefined, kind: RefKind) => {
    const end = start + text.length
    if (node && free(start, end)) found.push({ start, end, node, kind, text })
  }

  for (const m of line.matchAll(OBJREF)) {
    const text = m[0].replace(/\.+$/, '')
    add(m.index, text, objref(text, index), 'objref')
  }
  for (const m of line.matchAll(QUOTED))
    add(m.index, m[0], index.names.get(m[2].toUpperCase()), 'name')
  for (const m of line.matchAll(NUMBER)) {
    const end = m.index + m[0].length
    add(m.index, m[0], byId(index, m[0], line.slice(0, m.index), line.slice(end)), 'id')
  }
  for (const m of line.matchAll(CALL))
    add(m.index, m[0], index.packages.get(m[1].toUpperCase()), 'call')

  return found.sort((a, b) => a.start - b.start)
}

export const REF_KINDS: Record<RefKind, string> = {
  objref: 'Object reference',
  name: 'Referenced by name',
  id: 'Referenced by id',
  call: 'Package call',
}
