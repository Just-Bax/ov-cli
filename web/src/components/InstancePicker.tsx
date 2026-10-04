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

// Signed-in instances first; an empty value lets the agent pick from context.
export function InstancePicker({
  value,
  onChange,
  instances,
}: {
  value: string
  onChange: (v: string) => void
  instances: Instance[]
}) {
  const sorted = [...instances].sort(
    (a, b) => Number(b.valid) - Number(a.valid) || a.host.localeCompare(b.host),
  )
  return (
    <Dropdown
      value={value}
      onChange={onChange}
      variant="plain"
      prefix={<span className="text-faint font-normal">Instance</span>}
      options={[
        { value: '', label: 'Auto', hint: 'from context' },
        ...sorted.map((i) => ({
          value: i.alias,
          label: i.tenant ? `${i.host} / ${i.tenant}` : i.host,
          hint: i.valid ? '' : 'expired',
        })),
      ]}
    />
  )
}
