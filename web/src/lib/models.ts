import { useEffect, useState } from 'react'
import type { ModelInfo, Provider } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'
import { providerStatus, useSettings } from '@/lib/settings'

const cache = new Map<Provider, Promise<ModelInfo[]>>()
const listeners = new Set<() => void>()

export function loadModels(provider: Provider): Promise<ModelInfo[]> {
  const known = cache.get(provider)
  if (known) return known
  const loading = api.models(provider)
  cache.set(provider, loading)
  loading.catch(() => cache.delete(provider))
  return loading
}

export function forgetModels(provider: Provider): void {
  cache.delete(provider)
  for (const listener of listeners) listener()
}

export function useModels(provider: Provider): ModelInfo[] | undefined {
  const { providers } = useSettings()
  const signedIn = providerStatus(providers, provider).account.signedIn
  const [models, setModels] = useState<ModelInfo[]>()
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const reload = () => setVersion((v) => v + 1)
    listeners.add(reload)
    return () => {
      listeners.delete(reload)
    }
  }, [])

  useEffect(() => {
    if (!signedIn) {
      setModels([])
      return
    }

    let stale = false
    setModels(undefined)
    loadModels(provider).then((found) => !stale && setModels(found), reportError)

    return () => {
      stale = true
    }
  }, [provider, signedIn, version])

  return models
}

export function modelName(models: ModelInfo[] | undefined, id: string): string {
  return models?.find((m) => m.id === id)?.name ?? id
}
