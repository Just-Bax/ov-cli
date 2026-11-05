import { useCallback, useEffect, useRef, useState } from 'react'
import { reduce } from '@shared/reduce.ts'
import type { RunEvent, RunState, RunWindow, StoredEvent } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from './api'
import { prefetch, take } from './prefetch'

const RECONNECT_DELAY_MS = 2000
const PREFETCH_SLOT = 'run'
const TURNS_PAGE = 10

function loadRun(id: string) {
  return api.run(id, TURNS_PAGE)
}

export function prefetchRun(id: string): void {
  prefetch(PREFETCH_SLOT, id, () => loadRun(id))
}

function withOlder(state: RunState, older: RunWindow): RunState {
  return {
    ...state,
    start: older.start,
    items: [...older.items, ...state.items],
    chat: [...older.chat, ...state.chat],
    tools: [...older.tools, ...state.tools],
    changes: [...older.changes, ...state.changes],
    grids: [...older.grids, ...state.grids],
    questions: [...older.questions, ...state.questions],
    logins: [...older.logins, ...state.logins],
    compactions: [...older.compactions, ...state.compactions],
    outline: state.outline.filter((m) => m.start < older.start),
  }
}

export function useRun(id: string): {
  state?: RunState
  error?: string
  loadOlder: (until?: number) => Promise<void>
  loadingOlder: boolean
  apply: (event: RunEvent) => void
} {
  const [state, setState] = useState<RunState>()
  const [error, setError] = useState<string>()
  const [loadingOlder, setLoadingOlder] = useState(false)
  const current = useRef<RunState | undefined>(undefined)
  const loading = useRef(false)

  useEffect(() => {
    let closed = false
    let source: EventSource | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    let frame: number | undefined
    let seq = -1

    current.current = undefined
    setState(undefined)
    setError(undefined)

    const flush = () => {
      frame = undefined
      setState(current.current)
    }

    const connect = () => {
      source = new EventSource(api.runEventsUrl(id, seq))
      source.onmessage = (msg) => {
        const event = JSON.parse(msg.data as string) as StoredEvent
        if (!event.live && event.seq <= seq) return
        if (!event.live) seq = event.seq
        if (!current.current) return
        current.current = reduce(current.current, event)
        frame ??= requestAnimationFrame(flush)
      }
      source.onerror = () => {
        source?.close()
        if (!closed) retry = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    take(PREFETCH_SLOT, id, () => loadRun(id))
      .then(({ seq: at, ...snapshot }) => {
        if (closed) return
        seq = at
        current.current = snapshot
        setState(snapshot)
        connect()
      })
      .catch((e: Error) => !closed && setError(e.message))

    return () => {
      closed = true
      clearTimeout(retry)
      if (frame !== undefined) cancelAnimationFrame(frame)
      source?.close()
    }
  }, [id])

  const loadOlder = useCallback(
    async (until?: number) => {
      const now = current.current
      if (!now?.start || loading.current) return

      const starts = new Set(
        now.outline.filter((m) => until !== undefined && m.start >= until).map((m) => m.start),
      )

      loading.current = true
      setLoadingOlder(true)
      try {
        const older = await api.runHistory(id, now.start, Math.max(TURNS_PAGE, starts.size))
        const latest = current.current
        if (!latest || latest.summary.id !== id || latest.start !== now.start) return

        current.current = withOlder(latest, older)
        setState(current.current)
      } catch (e) {
        reportError(e)
      } finally {
        loading.current = false
        setLoadingOlder(false)
      }
    },
    [id],
  )

  const apply = useCallback((event: RunEvent) => {
    const now = current.current
    if (!now) return
    current.current = reduce(now, { seq: -1, ts: Date.now(), live: true, event })
    setState(current.current)
  }, [])

  return { state, error, loadOlder, loadingOlder, apply }
}
