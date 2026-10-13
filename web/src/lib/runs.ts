import { useSyncExternalStore } from 'react'
import type { RunList, RunStatus } from '@shared/types.ts'
import { reportError } from '@/components/Toasts'
import { api } from '@/lib/api'
import { remember } from '@/lib/undo'

const FALLBACK_POLL_MS = 60_000
const REFRESH_DEBOUNCE_MS = 150
export const SETTLED_PAGE = 50

export type StatusChange = {
  kind: 'status' | 'meta' | 'list'
  id?: string
  status?: RunStatus
  title?: string
}

let list: RunList | undefined
let raw = ''
let settledLimit = SETTLED_PAGE
let source: EventSource | undefined
let poll: ReturnType<typeof setInterval> | undefined
let pending: ReturnType<typeof setTimeout> | undefined
const listeners = new Set<() => void>()
const statusListeners = new Set<(change: StatusChange) => void>()

function publish(next: RunList) {
  list = next
  for (const listen of listeners) listen()
}

export function refreshRuns(): Promise<void> {
  return api
    .runs(settledLimit)
    .then((next) => {
      const text = JSON.stringify(next)
      if (text === raw) return
      raw = text
      publish(next)
    })
    .catch(reportError)
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
  source = new EventSource('/api/status-events')
  source.onopen = () => void refreshRuns()
  source.onmessage = (message) => {
    const change = JSON.parse(message.data as string) as StatusChange
    scheduleRefresh()
    for (const listen of statusListeners) listen(change)
  }
  poll = setInterval(onVisible, FALLBACK_POLL_MS)
  document.addEventListener('visibilitychange', onVisible)
}

function stopIfIdle() {
  if (listeners.size || statusListeners.size) return
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

export function onStatusChange(listen: (change: StatusChange) => void): () => void {
  statusListeners.add(listen)
  start()
  return () => {
    statusListeners.delete(listen)
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

export async function setSettled(id: string, settled: boolean, undoable = true): Promise<void> {
  if (list) {
    const run = [...list.active, ...list.snoozed, ...list.settled].find((r) => r.id === id)
    if (run) {
      const moved = { ...run, settled }
      const active = list.active.filter((r) => r.id !== id)
      const done = list.settled.filter((r) => r.id !== id)
      const byNewest = (a: { createdAt: number }, b: { createdAt: number }) =>
        b.createdAt - a.createdAt
      publish({
        ...list,
        active: settled ? active : [...active, moved].sort(byNewest),
        snoozed: list.snoozed.filter((r) => r.id !== id),
        settled: settled ? [...done, moved].sort(byNewest) : done,
        settledTotal: list.settledTotal + (settled ? 1 : -1),
      })
    }
  }
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

export async function setPinned(id: string, pinned: boolean, undoable = true): Promise<void> {
  await api.pinRun(id, pinned)
  await refreshRuns()
  if (undoable)
    remember(pinned ? 'Thread pinned' : 'Thread unpinned', () => setPinned(id, !pinned, false))
}

export async function setSnoozed(id: string, until: number | null, undoable = true): Promise<void> {
  const before = list?.snoozed.find((r) => r.id === id)?.snoozedUntil ?? null
  await api.snoozeRun(id, until)
  await refreshRuns()
  if (undoable)
    remember(until ? 'Thread snoozed' : 'Thread woken up', () =>
      setSnoozed(id, before && before > Date.now() ? before : null, false),
    )
}
