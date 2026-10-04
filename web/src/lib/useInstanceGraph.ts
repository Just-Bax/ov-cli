import { useEffect, useMemo, useState } from 'react'
import type { GraphStatus, InstanceGraph } from '@shared/types.ts'
import { useInstances } from '@/components/InstancePicker'
import { api } from '@/lib/api'

const INSTANCE_KEY = 'ov-agent.map-instance'
export const FOCUS_KEY = 'ov-agent.map-focus'

// One instance choice and one copy of its map for the Map and Explorer pages.
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
      .then((s) => alive && setStatus(s))
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [alias])

  // Follow a build until it finishes, then load the new map without clearing the view.
  useEffect(() => {
    if (!alias || !status) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    if (status.state === 'building') {
      timer = setTimeout(() => {
        api
          .graphStatus(alias)
          .then((s) => alive && setStatus(s))
          .catch(() => undefined)
      }, 2000)
    } else if (status.builtAt && graph?.builtAt !== status.builtAt) {
      api
        .graph(alias)
        .then((g) => alive && setGraph(g))
        .catch((e: Error) => alive && setError(e.message))
    }
    return () => {
      alive = false
      clearTimeout(timer)
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
  const label = current
    ? current.tenant
      ? `${current.host} / ${current.tenant}`
      : current.host
    : ''
  return { instances, signedIn, alias, setAlias, label, status, graph, error, build }
}
