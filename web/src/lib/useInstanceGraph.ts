import { useEffect, useMemo, useState } from 'react'
import type { GraphStatus, InstanceGraph } from '@shared/types.ts'
import { api } from '@/lib/api'
import { instanceLabel, useInstances } from '@/lib/instances'

const INSTANCE_KEY = 'ov-agent.map-instance'
const BUILD_POLL_MS = 2000
export const FOCUS_KEY = 'ov-agent.map-focus'

export function useInstanceGraph() {
  const { instances } = useInstances()
  const signedIn = useMemo(() => (instances ?? []).filter((i) => i.valid), [instances])
  const [alias, setAlias] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const [status, setStatus] = useState<GraphStatus>()
  const [graph, setGraph] = useState<InstanceGraph>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    if (instances && !signedIn.some((i) => i.alias === alias)) setAlias(signedIn[0]?.alias ?? '')
  }, [instances])

  useEffect(() => {
    if (alias) localStorage.setItem(INSTANCE_KEY, alias)
  }, [alias])

  useEffect(() => {
    if (!alias) return

    let alive = true
    setGraph(undefined)
    setError(undefined)
    setStatus(undefined)
    api
      .graphStatus(alias)
      .then(async (s) => {
        if (!alive) return
        setStatus(s)
        if (s.state !== 'ready') return

        const synced = await api.syncGraph(alias)
        if (alive) setStatus(synced)
      })
      .catch((e: Error) => alive && setError(e.message))

    return () => {
      alive = false
    }
  }, [alias])

  useEffect(() => {
    if (!alias || !status) return

    let alive = true
    let pollTimer: ReturnType<typeof setTimeout> | undefined
    const builtMapIsNewer = status.builtAt && graph?.builtAt !== status.builtAt
    if (status.state === 'building') {
      pollTimer = setTimeout(() => {
        api
          .graphStatus(alias)
          .then((s) => alive && setStatus(s))
          .catch((e: Error) => alive && setError(e.message))
      }, BUILD_POLL_MS)
    } else if (builtMapIsNewer) {
      api
        .graph(alias)
        .then((g) => alive && setGraph(g))
        .catch((e: Error) => alive && setError(e.message))
    }

    return () => {
      alive = false
      clearTimeout(pollTimer)
    }
  }, [alias, status])

  const build = async () => {
    setError(undefined)
    try {
      setStatus(await api.buildGraph(alias))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const current = signedIn.find((i) => i.alias === alias)
  const label = current ? instanceLabel(current) : ''
  const building = status?.state === 'building'
  const loading = !error && (!status || (Boolean(status.builtAt) && !graph && !building))

  return {
    instances,
    signedIn,
    alias,
    setAlias,
    label,
    status,
    graph,
    error,
    build,
    building,
    loading,
  }
}

export type InstanceGraphState = ReturnType<typeof useInstanceGraph>
