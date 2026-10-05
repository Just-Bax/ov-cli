import { createContext, useContext } from 'react'
import type { Settings } from '@shared/types.ts'

type SettingsValue = {
  settings: Settings
  update: (patch: Partial<Settings>) => Promise<void>
}

export const SettingsContext = createContext<SettingsValue | undefined>(undefined)

export function useSettings(): SettingsValue {
  const value = useContext(SettingsContext)
  if (!value) throw new Error('useSettings must be used inside SettingsContext.Provider')
  return value
}
