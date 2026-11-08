import { GearSix as Cog6ToothIcon } from '@phosphor-icons/react'
import { Skeleton } from '@/components/common/ui'
import { AccountButton, type SidebarAccount } from '@/components/layout/AccountMenu'
import { cn } from '@/lib/cn'
import { href } from '@/lib/route'

const FOOTER_INSET = 'pr-[9px] pl-3'
const ACCOUNT_INSET = 'pr-3 pl-2'

export function SidebarFooter({
  account,
  collapsed,
  onSettings,
}: {
  account?: SidebarAccount
  collapsed: boolean
  onSettings: boolean
}) {
  if (collapsed) {
    return (
      <div className="border-line-strong/60 flex h-16 shrink-0 items-center justify-center border-t">
        {account ? (
          <AccountButton account={account} collapsed active={onSettings} />
        ) : (
          <Skeleton className="size-8 rounded-full" />
        )}
      </div>
    )
  }

  return (
    <div
      className={cn(
        'border-line-strong/60 flex h-16 shrink-0 items-center gap-1 border-t',
        FOOTER_INSET,
      )}
    >
      {account ? (
        <AccountButton account={account} collapsed={false} active={onSettings} />
      ) : (
        <span className={cn('flex h-11 min-w-0 flex-1 items-center gap-2.5', ACCOUNT_INSET)}>
          <Skeleton className="size-8 rounded-full" />
          <span className="space-y-1.5">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-2.5 w-24" />
          </span>
        </span>
      )}
      <a
        href={href({ page: 'settings' })}
        aria-label="Settings"
        title="Settings"
        className={cn(
          'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors',
          onSettings
            ? 'bg-brand-soft text-brand-strong'
            : 'text-muted hover:bg-canvas hover:text-fg',
        )}
      >
        <Cog6ToothIcon className="size-[18px]" />
      </a>
    </div>
  )
}
