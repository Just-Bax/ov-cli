import { createContext, useContext } from 'react'
import type { CostUnit, Provider, ProviderStatus, Settings } from '@shared/types.ts'

type SettingsValue = {
  settings: Settings
  providers: ProviderStatus[]
  update: (patch: Partial<Settings>) => Promise<void>
}

export const SettingsContext = createContext<SettingsValue | undefined>(undefined)

export function useSettings(): SettingsValue {
  const value = useContext(SettingsContext)
  if (!value) throw new Error('useSettings must be used inside SettingsContext.Provider')
  return value
}

export function providerStatus(providers: ProviderStatus[], provider: Provider): ProviderStatus {
  const found = providers.find((p) => p.id === provider)
  if (!found) throw new Error(`The server does not know the provider ${provider}.`)
  return found
}

export function useProvider(provider: Provider): ProviderStatus {
  return providerStatus(useSettings().providers, provider)
}

export function useCostUnit(provider: Provider): CostUnit {
  return useProvider(provider).costUnit
}
