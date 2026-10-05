import { useEffect, useState } from 'react'
import type { ModelInfo } from '@shared/types.ts'
import { Dropdown } from '@/components/Dropdown'
import { api } from '@/lib/api'
import { reportError } from '@/components/Toasts'

let cache: Promise<ModelInfo[]> | undefined

export function useModels(): ModelInfo[] {
  const [models, setModels] = useState<ModelInfo[]>([])
  useEffect(() => {
    cache ??= api.models().catch((e: Error) => {
      cache = undefined
      reportError(e)
      return []
    })
    void cache.then(setModels)
  }, [])
  return models
}

function modelOptions(models: ModelInfo[]) {
  return models.map((m) => ({ value: m.id, label: m.name, hint: m.vendor }))
}

export function ModelPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const models = useModels()
  const options = modelOptions(models)
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
