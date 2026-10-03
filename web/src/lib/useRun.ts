import { useEffect, useRef, useState } from 'react'
import { emptyState, reduce } from '@shared/reduce.ts'
import type { RunState, StoredEvent } from '@shared/types.ts'
import { api } from './api'

/** Live run state: initial fetch, then replay + follow the event stream. */
export function useRun(id: string): { state?: RunState; error?: string; reload: () => void } {
  const [state, setState] = useState<RunState>()
  const [error, setError] = useState<string>()
  const [nonce, setNonce] = useState(0)
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
          // EventSource retries by itself unless the server closed it; then resume by hand.
          source.onerror = () => {
            if (closed || source?.readyState !== EventSource.CLOSED) return
            source.close()
            retry = setTimeout(connect, 2000)
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
  }, [id, nonce])

  return { state, error, reload: () => setNonce((n) => n + 1) }
}
