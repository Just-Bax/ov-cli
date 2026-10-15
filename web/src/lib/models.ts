import { useEffect, useState } from 'react'
import type { ModelInfo, Provider } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'

const cache = new Map<Provider, Promise<ModelInfo[]>>()

export function loadModels(provider: Provider): Promise<ModelInfo[]> {
  const known = cache.get(provider)
  if (known) return known

  const loading = api.models(provider)
  cache.set(provider, loading)
  loading.catch(() => cache.delete(provider))
  return loading
}

export function useModels(provider: Provider): ModelInfo[] {
  const [models, setModels] = useState<ModelInfo[]>([])

  useEffect(() => {
    let stale = false
    setModels([])
    loadModels(provider).then(
      (found) => !stale && setModels(found),
      (e: unknown) => reportError(e),
    )
    return () => {
      stale = true
    }
  }, [provider])

  return models
}

export function modelName(models: ModelInfo[], id: string): string {
  return models.find((m) => m.id === id)?.name ?? id
}
