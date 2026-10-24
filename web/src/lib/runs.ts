import { useSyncExternalStore } from 'react'
import type { RunList, RunStatus, RunSummary } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'
import { noteRuns, noteStatus, type StatusChange } from '@/lib/attention'
import { MINUTE_MS } from '@/lib/time'
import { remember } from '@/lib/undo'

const FALLBACK_POLL_MS = MINUTE_MS
const REFRESH_DEBOUNCE_MS = 150
const SETTLED_PAGE = 50

let list: RunList | undefined
let raw = ''
let settledLimit = SETTLED_PAGE
let source: EventSource | undefined
let poll: ReturnType<typeof setInterval> | undefined
let pending: ReturnType<typeof setTimeout> | undefined
let requested = 0
let applied = 0
const listeners = new Set<() => void>()

export const WORKING = new Set<RunStatus>(['queued', 'running', 'waiting'])

function publish(next: RunList) {
  list = next
  noteRuns(next)
  for (const listen of listeners) listen()
}

export function sidebarOrder(runs: RunSummary[]): RunSummary[] {
  const rest = runs.filter((r) => !r.pinned)
  return [
    ...runs.filter((r) => r.pinned),
    ...rest.filter((r) => WORKING.has(r.status)),
    ...rest.filter((r) => !WORKING.has(r.status)),
  ]
}

export function allRuns(runs: RunList | undefined): RunSummary[] {
  return [...(runs?.active ?? []), ...(runs?.snoozed ?? []), ...(runs?.settled ?? [])]
}

export function refreshRuns(): Promise<void> {
  const ticket = ++requested
  return api
    .runs(settledLimit)
    .then((next) => {
      if (ticket < applied) return
      applied = ticket
      const text = JSON.stringify(next)
      if (text === raw) return
      raw = text
      publish(next)
    })
    .catch(reportError)
}

function onChange(message: MessageEvent<string>) {
  const change = JSON.parse(message.data) as StatusChange | { kind: 'list' | 'meta' }
  if (change.kind === 'status') noteStatus(change)
  scheduleRefresh()
}

function scheduleRefresh() {
  clearTimeout(pending)
  pending = setTimeout(() => void refreshRuns(), REFRESH_DEBOUNCE_MS)
}

function onVisible() {
  if (document.visibilityState === 'visible') void refreshRuns()
}

function start() {
  if (source) return

  void refreshRuns()
  source = new EventSource(api.statusEventsUrl())
  source.onopen = () => void refreshRuns()
  source.onmessage = onChange
  poll = setInterval(onVisible, FALLBACK_POLL_MS)
  document.addEventListener('visibilitychange', onVisible)
}

function stopIfIdle() {
  if (listeners.size) return
  source?.close()
  source = undefined
  clearInterval(poll)
  clearTimeout(pending)
  document.removeEventListener('visibilitychange', onVisible)
}

function subscribe(listen: () => void): () => void {
  listeners.add(listen)
  start()
  return () => {
    listeners.delete(listen)
    stopIfIdle()
  }
}

export function useRuns(): RunList | undefined {
  return useSyncExternalStore(subscribe, () => list)
}

export function showMoreSettled(): Promise<void> {
  settledLimit += SETTLED_PAGE
  return refreshRuns()
}

function byNewest(a: RunSummary, b: RunSummary): number {
  return b.createdAt - a.createdAt
}

function moveLocally(id: string, settled: boolean) {
  const run = allRuns(list).find((r) => r.id === id)
  if (!list || !run) return

  const moved = { ...run, settled }
  const active = list.active.filter((r) => r.id !== id)
  const done = list.settled.filter((r) => r.id !== id)

  publish({
    ...list,
    active: settled ? active : [...active, moved].sort(byNewest),
    snoozed: list.snoozed.filter((r) => r.id !== id),
    settled: settled ? [...done, moved].sort(byNewest) : done,
    settledTotal: list.settledTotal + (settled ? 1 : -1),
  })
}

export async function setSettled(id: string, settled: boolean, undoable = true): Promise<void> {
  moveLocally(id, settled)

  try {
    await api.settleRun(id, settled)
  } finally {
    await refreshRuns()
  }

  if (undoable)
    remember(settled ? 'Thread settled' : 'Thread moved back', () =>
      setSettled(id, !settled, false),
    )
}

export function patchLocally(id: string, patch: Partial<RunSummary>) {
  if (!list) return

  const patched = (runs: RunSummary[]) => runs.map((r) => (r.id === id ? { ...r, ...patch } : r))
  publish({
    ...list,
    active: patched(list.active),
    snoozed: patched(list.snoozed),
    settled: patched(list.settled),
  })
}

function snoozeLocally(id: string, until: number | null) {
  const run = allRuns(list).find((r) => r.id === id)
  if (!list || !run) return

  const moved = { ...run, snoozedUntil: until ?? undefined }
  const active = list.active.filter((r) => r.id !== id)
  const snoozed = list.snoozed.filter((r) => r.id !== id)

  publish({
    ...list,
    active: until ? active : [...active, moved].sort(byNewest),
    snoozed: until ? [...snoozed, moved] : snoozed,
  })
}

export function removeLocally(id: string) {
  if (!list) return

  const kept = (runs: RunSummary[]) => runs.filter((r) => r.id !== id)
  const wasSettled = list.settled.some((r) => r.id === id)
  publish({
    ...list,
    active: kept(list.active),
    snoozed: kept(list.snoozed),
    settled: kept(list.settled),
    settledTotal: list.settledTotal - (wasSettled ? 1 : 0),
  })
}

export async function setPinned(id: string, pinned: boolean, undoable = true): Promise<void> {
  patchLocally(id, { pinned })

  try {
    await api.pinRun(id, pinned)
  } finally {
    await refreshRuns()
  }

  if (undoable)
    remember(pinned ? 'Thread pinned' : 'Thread unpinned', () => setPinned(id, !pinned, false))
}

export async function setSnoozed(id: string, until: number | null, undoable = true): Promise<void> {
  const before = list?.snoozed.find((r) => r.id === id)?.snoozedUntil ?? null
  snoozeLocally(id, until)

  try {
    await api.snoozeRun(id, until)
  } finally {
    await refreshRuns()
  }

  if (undoable)
    remember(until ? 'Thread snoozed' : 'Thread woken up', () =>
      setSnoozed(id, before && before > Date.now() ? before : null, false),
    )
}
