import type { Instance } from '@shared/types.ts'
import { Dropdown } from '@/components/common/Dropdown'
import { instanceLabel } from '@/lib/instances'

export function InstancePicker({
  value,
  onChange,
  instances,
}: {
  value: string
  onChange: (v: string) => void
  instances: Instance[]
}) {
  const signedInFirst = [...instances].sort(
    (a, b) => Number(b.valid) - Number(a.valid) || a.host.localeCompare(b.host),
  )

  return (
    <Dropdown
      value={value}
      onChange={onChange}
      variant="plain"
      fluid
      className="max-w-[320px]"
      prefix={<span className="text-faint font-normal">Instance</span>}
      options={[
        { value: '', label: 'Auto', hint: 'from context' },
        ...signedInFirst.map((i) => ({
          value: i.alias,
          label: instanceLabel(i),
          hint: i.valid ? '' : 'expired',
        })),
      ]}
    />
  )
}
