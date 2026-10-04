import { createContext, useContext } from 'react'
import type { Settings } from '@shared/types.ts'

export const DEFAULT_SETTINGS: Settings = {
  defaultModel: '',
  maxSteps: 80,
  notify: false,
  showTimeSaved: true,
  expandTools: false,
}

export const SettingsContext = createContext<{
  settings: Settings
  update: (patch: Partial<Settings>) => Promise<void>
}>({ settings: DEFAULT_SETTINGS, update: async () => undefined })

export function useSettings() {
  return useContext(SettingsContext)
}
