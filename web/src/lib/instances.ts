import { useCallback, useEffect, useState } from 'react'
import type { Instance } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'

export function useInstances() {
  const [instances, setInstances] = useState<Instance[]>()
  const reload = useCallback(() => api.instances().then(setInstances, reportError), [])
  useEffect(() => {
    void reload()
  }, [reload])
  return { instances, setInstances, reload }
}

export function instanceLabel(instance: Instance): string {
  return instance.tenant ? `${instance.host} / ${instance.tenant}` : instance.host
}

export function onePerHost(instances: Instance[]): Instance[] {
  const byHost = new Map<string, Instance>()
  const mainSignInsFirst = [...instances].sort(
    (a, b) => Number(Boolean(a.tenant)) - Number(Boolean(b.tenant)),
  )
  for (const i of mainSignInsFirst) if (!byHost.has(i.host)) byHost.set(i.host, i)

  return [...byHost.values()].sort((a, b) => a.host.localeCompare(b.host))
}
