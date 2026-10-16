import type { RunState, StoredEvent, ThreadItem } from './types.ts'

function upsert<T extends { id: string }>(list: T[], next: T, merge = false): T[] {
  const i = list.findIndex((x) => x.id === next.id)
  if (i < 0) return [...list, next]
  return list.map((x, j) => (j === i ? (merge ? { ...x, ...next } : next) : x))
}

function withItem(items: ThreadItem[], item: ThreadItem): ThreadItem[] {
  return items.some((x) => x.kind === item.kind && x.id === item.id) ? items : [...items, item]
}

export function reduce(state: RunState, { event, ts, seq }: StoredEvent): RunState {
  switch (event.type) {
    case 'cost':
      return { ...state, summary: { ...state.summary, cost: event.cost } }
    case 'status':
      return {
        ...state,
        summary: { ...state.summary, status: event.status, updatedAt: ts },
        error: event.status === 'error' ? event.error : state.error,
      }
    case 'meta':
      return {
        ...state,
        caseUrl: event.caseUrl ?? state.caseUrl,
        summary: {
          ...state.summary,
          title: event.title ?? state.summary.title,
          caseKey: event.caseKey ?? state.summary.caseKey,
          instance: event.instance ?? state.summary.instance,
        },
      }
    case 'tool':
      return {
        ...state,
        tools: upsert(state.tools, event.tool, true),
        items: withItem(state.items, { kind: 'tool', id: event.tool.id }),
      }
    case 'text': {
      const i = state.chat.findIndex((m) => m.id === event.messageId)
      const chat =
        i < 0
          ? [
              ...state.chat,
              { id: event.messageId, role: 'assistant' as const, text: event.delta, ts },
            ]
          : state.chat.map((m, j) => (j === i ? { ...m, text: m.text + event.delta } : m))

      return { ...state, chat, items: withItem(state.items, { kind: 'text', id: event.messageId }) }
    }
    case 'message': {
      const i = state.chat.findIndex((m) => m.id === event.messageId)
      const chat =
        i < 0
          ? [
              ...state.chat,
              {
                id: event.messageId,
                role: 'assistant' as const,
                text: event.text,
                ts: event.ts ?? ts,
                links: event.links,
              },
            ]
          : state.chat.map((m, j) => (j === i ? { ...m, text: event.text, links: event.links } : m))

      return { ...state, chat, items: withItem(state.items, { kind: 'text', id: event.messageId }) }
    }
    case 'user':
      return {
        ...state,
        queued: state.queued.filter((m) => m.id !== event.message.id),
        chat: [...state.chat.filter((m) => m.id !== event.message.id), event.message],
        items: withItem(state.items, { kind: 'user', id: event.message.id }),
      }
    case 'change':
      return {
        ...state,
        changes: upsert(state.changes, event.change),
        items: withItem(state.items, { kind: 'change', id: event.change.id }),
      }
    case 'edit':
      return { ...state, edits: upsert(state.edits, event.edit) }
    case 'outcome': {
      const id = `o${seq}`
      return {
        ...state,
        outcome: event.outcome,
        outcomeId: id,
        items: withItem(state.items, { kind: 'outcome', id }),
      }
    }
    case 'question':
      return {
        ...state,
        questions: upsert(state.questions, event.question),
        items: withItem(state.items, { kind: 'question', id: event.question.id }),
      }
    case 'login':
      return {
        ...state,
        logins: upsert(state.logins, event.login),
        items: withItem(state.items, { kind: 'login', id: event.login.id }),
      }
    case 'queued':
      return {
        ...state,
        queued: [...state.queued.filter((m) => m.id !== event.message.id), event.message],
      }
    case 'unqueue':
      return { ...state, queued: state.queued.filter((m) => m.id !== event.id) }
    case 'rewind': {
      const i = state.items.findIndex((x) => x.kind === 'user' && x.id === event.itemId)
      if (i < 0) return state

      const items = state.items.slice(0, i)
      const keep = new Set(items.map((x) => `${x.kind}:${x.id}`))
      const outcomeKept = state.outcomeId && keep.has(`outcome:${state.outcomeId}`)

      return {
        ...state,
        items,
        chat: state.chat.filter((m) => keep.has(`${m.role === 'user' ? 'user' : 'text'}:${m.id}`)),
        outcome: outcomeKept ? state.outcome : undefined,
        outcomeId: outcomeKept ? state.outcomeId : undefined,
      }
    }
    case 'access':
      return { ...state, access: event.access }
    case 'browser':
      return { ...state, browser: { open: false, ...state.browser, ...event.browser } }
    default:
      return state
  }
}
