import { useRef } from 'react'
import type {
  ApprovalQuestion,
  ChatMessage,
  Question,
  RunState,
  ThreadItem,
  ToolActivity,
} from '@shared/types.ts'
import { isBrowserTool } from './BrowserPane'
import { summarize } from './ToolGroup'

export const LIVE_QUESTION = new Set(['running', 'waiting'])

const RESULT_ITEMS = new Set<ThreadItem['kind']>(['change', 'grid', 'outcome', 'compact'])

export type Block =
  | { kind: 'tools'; tools: ToolActivity[]; key: string }
  | { kind: 'item'; item: ThreadItem; key: string }

export interface Turn {
  user?: ChatMessage
  start: number
  blocks: Block[]
}

export function inheritedTurn(turn: Turn, state: RunState): boolean {
  return turn.start < (state.inheritedItems ?? 0)
}

export function inheritedTurnCount(state: RunState, turns: Turn[]): number {
  const inherited = state.inheritedItems ?? 0
  const older = state.outline.filter((m) => m.kind === 'user' && m.start < inherited).length
  return older + turns.filter((t) => t.user && t.start < inherited).length
}

export function freshBranchTurns(state: RunState, inheritedTurns: number): number {
  const inherited = state.inheritedItems ?? 0
  if (!inherited || state.summary.origin !== 'branch') return 0
  const own = state.items.slice(Math.max(0, inherited - state.start))
  return own.some((item) => item.kind === 'user' || item.kind === 'compact') ? 0 : inheritedTurns
}

export function nextTurnId(turns: Turn[], index: number): string | undefined {
  return turns.slice(index + 1).find((t) => t.user && !t.user.steer)?.user?.id
}

function indexed<T extends { id: string }>(cache: WeakMap<T[], Map<string, T>>, list: T[]) {
  const found = cache.get(list)
  if (found) return found
  const made = new Map(list.map((x) => [x.id, x]))
  cache.set(list, made)
  return made
}

const chatIndex = new WeakMap<ChatMessage[], Map<string, ChatMessage>>()
const changeIndex = new WeakMap<RunState['changes'], Map<string, RunState['changes'][number]>>()
const turnCache = new WeakMap<ThreadItem[], { chat: unknown; tools: unknown; turns: Turn[] }>()

export function chatById(state: RunState) {
  return indexed(chatIndex, state.chat)
}

export function changeById(state: RunState) {
  return indexed(changeIndex, state.changes)
}

export function toTurns(state: RunState): Turn[] {
  const cached = turnCache.get(state.items)
  if (cached && cached.chat === state.chat && cached.tools === state.tools) return cached.turns
  const turns = buildTurns(state)
  turnCache.set(state.items, { chat: state.chat, tools: state.tools, turns })
  return turns
}

function buildTurns(state: RunState): Turn[] {
  const chat = chatById(state)
  const tools = new Map(state.tools.map((t) => [t.id, t]))
  const turns: Turn[] = [{ start: state.start, blocks: [] }]
  for (const [index, item] of state.items.entries()) {
    const turn = turns.at(-1)!
    if (item.kind === 'user') {
      const user = chat.get(item.id)
      if (user) turns.push({ user, start: state.start + index, blocks: [] })
      continue
    }

    if (item.kind === 'tool') {
      const tool = tools.get(item.id)
      if (!tool) continue

      const last = turn.blocks.at(-1)
      if (last?.kind === 'tools') last.tools.push(tool)
      else turn.blocks.push({ kind: 'tools', tools: [tool], key: `t_${item.id}` })
    } else {
      turn.blocks.push({ kind: 'item', item, key: `${item.kind}_${item.id}` })
    }
  }

  return turns.filter((t) => t.user || t.blocks.length)
}

function turnKeys(turn: Turn): string[] {
  return [...(turn.user ? [turn.user.id] : []), ...turn.blocks.map((b) => b.key)]
}

export function useArrivedLive(state: RunState | undefined): (turn: Turn, key: string) => boolean {
  const opened = useRef<{ from: number; keys: Set<string> }>(undefined)
  if (state && !opened.current) {
    const last = toTurns(state).at(-1)
    opened.current = { from: last?.start ?? state.start, keys: new Set(last ? turnKeys(last) : []) }
  }

  return (turn, key) =>
    opened.current !== undefined &&
    turn.start >= opened.current.from &&
    !opened.current.keys.has(key)
}

export function splitTurn(blocks: Block[]): { work: Block[]; result: Block[] } {
  const lastTools = blocks.findLastIndex((b) => b.kind === 'tools')
  if (lastTools < 0) return { work: [], result: blocks }

  const lastText = blocks.findLastIndex((b) => b.kind === 'item' && b.item.kind === 'text')
  const cut = lastText > lastTools || lastText < 0 ? lastTools + 1 : lastText
  const done = blocks.slice(0, cut)
  const kept = (b: Block) => b.kind === 'item' && RESULT_ITEMS.has(b.item.kind)

  return {
    work: done.filter((b) => !kept(b)),
    result: [...done.filter(kept), ...blocks.slice(cut)],
  }
}

export function workSummary(work: Block[], state: RunState): string {
  const tools = work.flatMap((b) => (b.kind === 'tools' ? b.tools : []))

  const updates = work.filter(
    (b) =>
      b.kind === 'item' && b.item.kind === 'text' && chatById(state).get(b.item.id)?.text.trim(),
  ).length

  const said = updates ? [`${updates} ${updates === 1 ? 'update' : 'updates'}`] : []
  return [summarize(tools), ...said].filter(Boolean).join(', ')
}

export function turnSpan(turn: Turn, state: RunState): number | undefined {
  const tools = turn.blocks.flatMap((b) => (b.kind === 'tools' ? b.tools : []))
  const texts = turn.blocks.flatMap((b) =>
    b.kind === 'item' && b.item.kind === 'text' ? [chatById(state).get(b.item.id)?.ts ?? 0] : [],
  )

  const starts = tools.flatMap((t) => (t.startedAt ? [t.startedAt] : []))
  const start = turn.user?.ts ?? Math.min(...starts, ...texts.filter(Boolean))
  const end = Math.max(...texts, ...tools.map((t) => (t.startedAt ?? 0) + (t.ms ?? 0)))
  return Number.isFinite(start) && end > start ? end - start : undefined
}

export function blocksText(blocks: Block[], state: RunState): string {
  const parts: string[] = []
  for (const b of blocks) {
    if (b.kind !== 'item') continue

    if (b.item.kind === 'text') {
      const t = chatById(state).get(b.item.id)?.text.trim()
      if (t) parts.push(t)
    } else if (b.item.kind === 'outcome' && b.item.id === state.outcomeId && state.outcome) {
      for (const i of state.outcome.issues) parts.push(`${i.title}: ${i.summary}`)
      if (state.outcome.reply) parts.push(state.outcome.reply)
    } else if (b.item.kind === 'grid') {
      const grid = state.grids.find((g) => g.id === b.item.id)
      if (grid) parts.push(grid.title)
    } else if (b.item.kind === 'change') {
      const ch = changeById(state).get(b.item.id)
      if (ch) parts.push(`${ch.title}\n${ch.after}`)
    }
  }

  return parts.join('\n\n')
}

export function turnTime(turn: Turn, state: RunState): number | undefined {
  for (let i = turn.blocks.length - 1; i >= 0; i--) {
    const b = turn.blocks[i]
    if (b.kind === 'item' && b.item.kind === 'text') return chatById(state).get(b.item.id)?.ts
  }
  return undefined
}

export function isThinking(state: RunState, turns: Turn[]): boolean {
  const lastBlock = turns.at(-1)?.blocks.at(-1)
  return (
    state.summary.status === 'running' &&
    !(lastBlock?.kind === 'tools' && lastBlock.tools.some((t) => t.status === 'running')) &&
    !(lastBlock?.kind === 'item' && lastBlock.item.kind === 'text') &&
    !state.compactions.some((c) => c.status === 'running')
  )
}

export function isOpen(question: Question): boolean {
  return !question.answers && !question.stopped
}

export function browserQuestion(state: RunState): ApprovalQuestion | undefined {
  if (!state.browser?.open || !LIVE_QUESTION.has(state.summary.status)) return undefined

  const tools = new Map(state.tools.map((t) => [t.id, t.name]))

  return state.questions.find(
    (q): q is ApprovalQuestion =>
      q.kind === 'approval' &&
      isOpen(q) &&
      Boolean(q.toolId) &&
      isBrowserTool(tools.get(q.toolId ?? '')),
  )
}

export function dockedQuestion(state: RunState): Question | undefined {
  if (!LIVE_QUESTION.has(state.summary.status)) return undefined
  const inBrowser = browserQuestion(state)?.id
  return state.questions.find((q) => isOpen(q) && q.id !== inBrowser)
}

export function browserShown(
  state: RunState | undefined,
  hiddenSession: number | undefined,
): boolean {
  if (!state?.browser?.open) return false
  return state.browser.session !== hiddenSession || Boolean(browserQuestion(state))
}
