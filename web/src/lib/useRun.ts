import { useEffect, useRef, useState } from 'react'
import { emptyState, reduce } from '@shared/reduce.ts'
import type { RunState, StoredEvent } from '@shared/types.ts'
import { api } from './api'

const RECONNECT_DELAY_MS = 2000

export function useRun(id: string): { state?: RunState; error?: string } {
  const [state, setState] = useState<RunState>()
  const [error, setError] = useState<string>()
  const seqRef = useRef(-1)

  useEffect(() => {
    let closed = false
    let source: EventSource | undefined
    let retry: ReturnType<typeof setTimeout> | undefined

    setState(undefined)
    setError(undefined)
    seqRef.current = -1

    api
      .run(id)
      .then((initial) => {
        if (closed) return

        let current: RunState = {
          ...emptyState(initial.summary, initial.input),
          feedback: initial.feedback,
        }
        setState(current)

        const connect = () => {
          source = new EventSource(`/api/runs/${id}/events?after=${seqRef.current}`)
          source.onmessage = (msg) => {
            const event = JSON.parse(msg.data) as StoredEvent
            if (event.seq <= seqRef.current) return

            seqRef.current = event.seq
            current = reduce(current, event)
            setState(current)
          }
          source.onerror = () => {
            const closedByServer = source?.readyState === EventSource.CLOSED
            if (closed || !closedByServer) return

            source?.close()
            retry = setTimeout(connect, RECONNECT_DELAY_MS)
          }
        }

        connect()
      })
      .catch((e: Error) => !closed && setError(e.message))

    return () => {
      closed = true
      clearTimeout(retry)
      source?.close()
    }
  }, [id])

  return { state, error }
}
