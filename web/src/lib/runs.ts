import { useSyncExternalStore } from 'react'
import type { RunSummary } from '@shared/types.ts'
import { reportError } from '@/components/Toasts'
import { api } from '@/lib/api'

const POLL_MS = 3000

let runs: RunSummary[] | undefined
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setInterval> | undefined

export function refreshRuns(): Promise<void> {
  return api
    .runs()
    .then((next) => {
      runs = next
      for (const listen of listeners) listen()
    })
    .catch(reportError)
}

function subscribe(listen: () => void): () => void {
  listeners.add(listen)
  if (listeners.size === 1) {
    void refreshRuns()
    timer = setInterval(() => void refreshRuns(), POLL_MS)
  }
  return () => {
    listeners.delete(listen)
    if (!listeners.size) clearInterval(timer)
  }
}

export function useRuns(): RunSummary[] | undefined {
  return useSyncExternalStore(subscribe, () => runs)
}

export async function setSettled(id: string, settled: boolean): Promise<void> {
  runs = runs?.map((r) => (r.id === id ? { ...r, settled } : r))
  for (const listen of listeners) listen()
  try {
    await api.settleRun(id, settled)
  } finally {
    await refreshRuns()
  }
}
