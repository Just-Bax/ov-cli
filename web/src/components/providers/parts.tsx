import type { ComponentType, ReactNode } from 'react'
import type { ProviderAccount } from '@shared/types.ts'
import type { SidebarAccount } from '@/components/layout/Sidebar'

export interface ProviderUi {
  usageTitle: string
  usageNote: string
  accountBadge: ReactNode
  summary: (account: ProviderAccount) => string
  sidebar: (account: ProviderAccount) => Omit<SidebarAccount, 'provider'>
  accountDetail: (account: ProviderAccount, runsAgent: boolean) => string
  SignIn: ComponentType<{ account: ProviderAccount; onRefresh: () => void }>
  Plan: ComponentType
  AccountAction?: ComponentType<{ account: ProviderAccount; onChange: () => void }>
}

export function capitalized(text: string): string {
  return `${text[0].toUpperCase()}${text.slice(1)}`
}

export function PlanRow({
  title,
  action,
  children,
}: {
  title: string
  action: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex items-start gap-4">
      <div className="min-w-0 flex-1">
        <div className="text-fg text-[13px] font-medium">{title}</div>
        <div className="text-muted mt-0.5 text-[12px] leading-relaxed">{children}</div>
      </div>
      {action}
    </div>
  )
}
