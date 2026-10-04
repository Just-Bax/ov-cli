import type { GraphNode, GraphNodeType } from '@shared/types.ts'
import type { Index } from '@/components/map/meta'

export type RefKind = 'objref' | 'name' | 'id' | 'call'
export type Ref = { start: number; end: number; node: GraphNode; kind: RefKind; text: string }
export type RefIndex = {
  objrefs: Map<string, GraphNode>
  names: Map<string, GraphNode>
  ids: Map<number, GraphNode>
  packages: Map<string, GraphNode>
}

// Keep in sync with graph.py: the same four kinds of reference count as links there.
const OBJREF = /\bid\.[A-Za-z0-9_.]+/gi
const QUOTED = /(['"])([A-Za-z][A-Za-z0-9_$#]{2,})\1/g
const NUMBER = /\b\d{6,12}\b/g
const CALL = /\b([A-Za-z][A-Za-z0-9_$#]*)(?=\s*\.\s*[A-Za-z])/g
const OBJREF_KINDS: Record<string, GraphNodeType> = { imp: 'import', rpt: 'report', wf: 'workflow' }
const NAMED: GraphNodeType[] = ['field', 'trackor_type', 'db_package']

// The platform builds references as id.<name> with names lowercased and spaces as underscores.
const key = (name: string) => name.toLowerCase().replace(/ /g, '_')

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
    if (n.type === 'trackor_type') objrefs.set(`id.${key(n.name)}.tt`, n)
    else if (n.type === 'field') {
      const owner = idx?.links.get(n.id)?.find((l) => l.kind === 'field_of' && l.out)?.other
      if (owner) objrefs.set(`id.${key(owner.name)}.cf.${key(n.name)}`, n)
    } else {
      const prefix = Object.entries(OBJREF_KINDS).find(([, t]) => t === n.type)?.[0]
      if (prefix) objrefs.set(`id.${prefix}.${key(n.name)}`, n)
    }
  }
  return {
    objrefs,
    names: unique(
      nodes
        .filter((n) => NAMED.includes(n.type) && n.name.length > 3)
        .map((n) => [n.name.toUpperCase(), n]),
    ),
    ids: unique(nodes.map((n) => [n.ref, n])),
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
  // id.<type>.tt, and the type behind id.<type>.rel.* or id.<type>.class.*.
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
  for (const m of line.matchAll(NUMBER)) add(m.index, m[0], index.ids.get(Number(m[0])), 'id')
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
