import { useCallback, useEffect, useState } from 'react'
import type { Instance, InstanceAccess, PlatformEdition } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'

const CHECKING_POLL_MS = 1500

const EDITIONS: Record<PlatformEdition, string> = {
  STANDARD: 'Standard',
  ENTERPRISE: 'Enterprise',
  PREMIUM: 'Premium',
  AI_ENABLED: 'AI Enabled',
}

const CAPABILITIES: [keyof InstanceAccess, string][] = [
  ['testSql', 'Test SQL'],
  ['export', 'Export'],
  ['import', 'Import'],
  ['metadata', 'Schema'],
  ['dbSource', 'DB source'],
  ['mcp', 'MCP'],
]

export function useInstances() {
  const [instances, setInstances] = useState<Instance[]>()
  const reload = useCallback(() => api.instances().then(setInstances, reportError), [])
  useEffect(() => {
    void reload()
  }, [reload])

  const checking = instances?.some((i) => i.access.checking)
  useEffect(() => {
    if (!checking) return
    const timer = setTimeout(() => void reload(), CHECKING_POLL_MS)
    return () => clearTimeout(timer)
  }, [checking, instances, reload])

  return { instances, setInstances, reload }
}

export function editionLabel(access: InstanceAccess): string | undefined {
  return access.edition ? EDITIONS[access.edition] : undefined
}

export function allowedLabels(access: InstanceAccess): { label: string; on: boolean }[] {
  return CAPABILITIES.map(([key, label]) => ({ label, on: Boolean(access[key]) }))
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
