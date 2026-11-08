import type { Provider, ProviderStatus, Status } from '@shared/types.ts'
import type { SidebarAccount } from '@/components/layout/AccountMenu'
import { providerStatus } from '@/lib/settings'
import { CLAUDE_UI } from './claude'
import { COPILOT_UI } from './copilot'
import type { ProviderUi } from './parts'

export const PROVIDER_UI: Record<Provider, ProviderUi> = {
  claude: CLAUDE_UI,
  copilot: COPILOT_UI,
}

export function currentProvider(status: Status): ProviderStatus {
  return providerStatus(status.providers, status.provider)
}

export function providerReady(status: Status): boolean {
  return currentProvider(status).account.signedIn
}

export function providerSummary(status: Status): string {
  const current = currentProvider(status)
  return PROVIDER_UI[current.id].summary(current.account)
}

export function sidebarAccount(status: Status): SidebarAccount {
  const current = currentProvider(status)
  return {
    name: status.settings.fullName,
    provider: current.id,
    unit: current.costUnit,
    instances: status.instances,
    version: status.ov.version,
  }
}
