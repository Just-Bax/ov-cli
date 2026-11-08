import { Extension, type JSONContent, Node } from '@tiptap/core'
import type { Fragment, Node as PmNode } from '@tiptap/pm/model'
import { type EditorState, Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { NodeViewWrapper, type ReactNodeViewProps, ReactNodeViewRenderer } from '@tiptap/react'
import { TYPES } from '@/components/map/meta'
import { type Mention, type MentionKind, mentionText, splitMentions } from '@/lib/mentions'
import { findRefs, type RefIndex } from '@/lib/references'
import { MentionChip } from './MentionChip'

export const MENTION_NODE = 'mention'
const LEAF = '￼'
const SLASH = /^\/([\w-]*)(?: ([^\n￼]*))?$/
const INLINE_TRIGGER = /(?:^|\s)([@$])([^\s￼]*)$/
const AMOUNT = /^\d/

export type TriggerChar = '/' | '@' | '$'
export interface Trigger {
  char: TriggerChar
  query: string
  command?: string
  from: number
  to: number
}

function MentionView({ node, selected }: ReactNodeViewProps) {
  return (
    <NodeViewWrapper as="span" className="inline">
      <MentionChip mention={node.attrs as Mention} selected={selected} />
    </NodeViewWrapper>
  )
}

export const MentionNode = Node.create({
  name: MENTION_NODE,
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      kind: { default: null },
      target: { default: null },
      label: { default: null },
    }
  },
  parseHTML() {
    return [{ tag: 'span[data-mention]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['span', { ...HTMLAttributes, 'data-mention': '' }]
  },
  renderText({ node }) {
    return mentionText(node.attrs as Mention)
  },
  addNodeView() {
    return ReactNodeViewRenderer(MentionView, { as: 'span' })
  },
})

export function mentionNode(mention: Mention): JSONContent {
  return { type: MENTION_NODE, attrs: { ...mention } }
}

export function lineContent(line: string): JSONContent[] {
  return splitMentions(line).map((part) =>
    typeof part === 'string' ? { type: 'text', text: part } : mentionNode(part),
  )
}

export function paragraphsOf(text: string): JSONContent[] {
  return text.split('\n').map((line) => {
    const content = lineContent(line)
    return content.length ? { type: 'paragraph', content } : { type: 'paragraph' }
  })
}

export function docOf(text: string): JSONContent {
  return { type: 'doc', content: paragraphsOf(text) }
}

function leafText(node: PmNode, source: boolean): string {
  if (node.isText) return node.text ?? ''
  return source && node.type.name === MENTION_NODE ? mentionText(node.attrs as Mention) : LEAF
}

function inlineText(content: Fragment, source: boolean): string {
  let text = ''
  content.forEach((child) => {
    text += leafText(child, source)
  })

  return text
}

export function textOf(content: Fragment): string {
  const lines: string[] = []
  let inline = ''
  content.forEach((node) => {
    if (node.isBlock) lines.push(inlineText(node.content, true))
    else inline += leafText(node, true)
  })

  return inline || lines.join('\n')
}

export function mentionsIn(doc: PmNode, kind: MentionKind): Set<string> {
  const found = new Set<string>()
  doc.descendants((node) => {
    if (node.type.name === MENTION_NODE && node.attrs.kind === kind) found.add(node.attrs.target)
  })

  return found
}

export function mentionRanges(doc: PmNode, kind: MentionKind, target: string): [number, number][] {
  const ranges: [number, number][] = []
  doc.descendants((node, pos) => {
    if (node.type.name === MENTION_NODE && node.attrs.kind === kind && node.attrs.target === target)
      ranges.push([pos, pos + node.nodeSize])
  })

  return ranges
}

export function triggerAt(state: EditorState): Trigger | undefined {
  const { selection, doc } = state
  if (!selection.empty) return undefined

  const $from = selection.$from
  const before = $from.parent.textBetween(0, $from.parentOffset, undefined, LEAF)

  const slash = doc.firstChild === $from.parent ? SLASH.exec(before) : null
  if (slash)
    return slash[2] === undefined
      ? { char: '/', query: slash[1], from: $from.start(), to: $from.pos }
      : { char: '/', command: slash[1], query: slash[2], from: $from.start(), to: $from.pos }

  const inline = INLINE_TRIGGER.exec(before)
  if (!inline) return undefined

  const [, char, query] = inline
  if (char === '$' && AMOUNT.test(query)) return undefined

  return { char: char as TriggerChar, query, from: $from.pos - query.length - 1, to: $from.pos }
}

export function atDocStart(state: EditorState): boolean {
  return state.selection.empty && state.selection.from <= 1
}

export function atDocEnd(state: EditorState): boolean {
  return state.selection.empty && state.selection.to >= state.doc.content.size - 1
}

const refsKey = new PluginKey('composer-refs')

function refDecorations(doc: PmNode, index: RefIndex | undefined): DecorationSet {
  if (!index) return DecorationSet.empty

  const decorations: Decoration[] = []
  doc.forEach((block, offset) => {
    for (const ref of findRefs(inlineText(block.content, false), index))
      decorations.push(
        Decoration.inline(offset + 1 + ref.start, offset + 1 + ref.end, {
          class: 'composer-ref',
          title: `${TYPES[ref.node.type].label}: ${ref.node.name} (${ref.node.ref})`,
        }),
      )
  })

  return DecorationSet.create(doc, decorations)
}

export const RefHighlight = Extension.create<{ index: () => RefIndex | undefined }>({
  name: 'composerRefs',
  addOptions() {
    return { index: () => undefined }
  },
  addProseMirrorPlugins() {
    const { index } = this.options
    return [
      new Plugin({
        key: refsKey,
        props: { decorations: (state) => refDecorations(state.doc, index()) },
      }),
    ]
  },
})
