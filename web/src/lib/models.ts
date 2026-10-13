import { useEffect, useState } from 'react'
import type { ModelInfo } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'

let cache: Promise<ModelInfo[]> | undefined

export function useModels(): ModelInfo[] {
  const [models, setModels] = useState<ModelInfo[]>([])

  useEffect(() => {
    cache ??= api.models()
    cache.then(setModels, (e: unknown) => {
      cache = undefined
      reportError(e)
    })
  }, [])

  return models
}

export function modelName(models: ModelInfo[], id: string): string {
  return models.find((m) => m.id === id)?.name ?? id
}
