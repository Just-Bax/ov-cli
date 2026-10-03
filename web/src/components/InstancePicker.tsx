import { useEffect, useState } from 'react'
import type { Instance } from '@shared/types.ts'
import { Dropdown } from '@/components/Dropdown'
import { api } from '@/lib/api'

export function useInstances(): { instances?: Instance[]; reload: () => void } {
  const [instances, setInstances] = useState<Instance[]>()
  const load = () =>
    api
      .instances()
      .then(setInstances)
      .catch(() => setInstances([]))
  useEffect(() => {
    void load()
  }, [])
  return { instances, reload: () => void load() }
}

export function defaultInstance(instances: Instance[], preferred: string): string {
  if (preferred && instances.some((i) => i.alias === preferred)) return preferred
  return instances.find((i) => i.current)?.alias ?? instances[0]?.alias ?? ''
}

export function InstancePicker({
  value,
  onChange,
  instances,
}: {
  value: string
  onChange: (v: string) => void
  instances: Instance[]
}) {
  return (
    <Dropdown
      value={value}
      onChange={onChange}
      variant="plain"
      placeholder="No instance"
      prefix={<span className="text-faint font-normal">Instance</span>}
      options={instances.map((i) => ({
        value: i.alias,
        label: i.alias,
        hint: i.valid ? i.host : 'expired',
      }))}
    />
  )
}
