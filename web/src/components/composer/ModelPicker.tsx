import { Dropdown } from '@/components/common/Dropdown'
import { useModels } from '@/lib/models'

export function ModelPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const models = useModels()
  const options = models.map((m) => ({ value: m.id, label: m.name, hint: m.vendor }))
  if (value && !options.some((o) => o.value === value))
    options.unshift({ value, label: value, hint: '' })

  return (
    <Dropdown
      value={value}
      onChange={onChange}
      options={options}
      variant="plain"
      prefix={<span className="text-faint font-normal">Model</span>}
    />
  )
}
