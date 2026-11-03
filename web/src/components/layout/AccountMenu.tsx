import { Check as CheckIcon } from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { CostUnit, Provider } from '@shared/types.ts'
import { ProviderBubble } from '@/components/common/ProviderLogo'
import { reportError } from '@/components/common/Toasts'
import { PROVIDER_UI } from '@/components/providers'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatAmount } from '@/lib/cost'
import { useClickOutside, useLoad } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'
import { useRuns, WORKING } from '@/lib/runs'
import { useSettings } from '@/lib/settings'

const MENU_WIDTH = 296
const MENU_GAP = 8
const INITIALS = 2

export type SidebarAccount = {
  name: string
  provider: Provider
  unit: CostUnit
  instances: { total: number; valid: number }
  version: string
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  return words
    .slice(0, INITIALS)
    .map((w) => w[0].toUpperCase())
    .join('')
}

function useToday(provider: Provider): number | undefined {
  const runs = useRuns()
  const busy = (runs?.active ?? [])
    .filter((r) => WORKING.has(r.status))
    .map((r) => r.id)
    .join()
  const { value } = useLoad(() => api.cost('month', provider), [provider, busy])
  return value ? (value.days.at(-1)?.amount ?? 0) : undefined
}

export function UserAvatar({ name, className }: { name?: string; className?: string }) {
  return (
    <span
      className={cn(
        'from-brand to-brand-strong flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-[12px] font-semibold text-white',
        className,
      )}
    >
      {name ? initials(name) : null}
    </span>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-line border-t py-1.5">
      <div className="text-faint px-2.5 py-1 text-[10.5px] font-semibold tracking-wide uppercase">
        {label}
      </div>
      {children}
    </div>
  )
}

function Row({
  children,
  trailing,
  onClick,
}: {
  children: ReactNode
  trailing?: ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="text-text hover:bg-canvas flex h-8 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[12.5px] transition-colors"
    >
      <span className="flex min-w-0 flex-1 items-center gap-2.5">{children}</span>
      {trailing ? <span className="text-faint shrink-0 text-[11px]">{trailing}</span> : null}
    </button>
  )
}

function Providers({ onPicked }: { onPicked: () => void }) {
  const { settings, providers, update } = useSettings()
  const ready = providers.filter((p) => p.account.signedIn)

  const pick = (provider: Provider) => {
    onPicked()
    if (provider !== settings.provider) void update({ provider }).catch(reportError)
  }

  return ready.map((p) => (
    <Row
      key={p.id}
      onClick={() => pick(p.id)}
      trailing={
        p.id === settings.provider ? (
          <CheckIcon weight="bold" className="text-brand-strong size-3.5" />
        ) : (
          PROVIDER_UI[p.id].plan(p.account)
        )
      }
    >
      <ProviderBubble provider={p.id} className="size-[18px]" />
      <span className={cn('truncate', p.id === settings.provider && 'text-fg font-medium')}>
        {PROVIDER_BRANDS[p.id].name}
      </span>
    </Row>
  ))
}

function Menu({ account, onClose }: { account: SidebarAccount; onClose: () => void }) {
  return (
    <>
      <div className="flex items-center gap-2.5 px-2.5 pt-2 pb-2.5">
        <UserAvatar name={account.name} />
        <div className="min-w-0">
          <div className="text-fg truncate text-[13px] font-semibold">{account.name}</div>
          <div className="text-faint text-[11.5px]">{account.version}</div>
        </div>
      </div>
      <Section label="Provider">
        <Providers onPicked={onClose} />
      </Section>
    </>
  )
}

export function AccountButton({
  account,
  collapsed,
  active,
}: {
  account: SidebarAccount
  collapsed: boolean
  active: boolean
}) {
  const [pos, setPos] = useState<{ left: number; bottom: number }>()
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const spent = useToday(account.provider)
  const close = () => setPos(undefined)

  useClickOutside([menu, trigger], close, Boolean(pos))
  useLayer(close, Boolean(pos))

  useEffect(() => {
    if (!pos) return
    window.addEventListener('resize', close)
    return () => window.removeEventListener('resize', close)
  }, [pos])

  const toggle = () => {
    if (pos) return close()
    const box = trigger.current?.getBoundingClientRect()
    if (!box) return
    setPos({ left: box.left, bottom: window.innerHeight - box.top + MENU_GAP })
  }

  const today = spent === undefined ? undefined : formatAmount(spent, account.unit)

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="Account"
        aria-expanded={Boolean(pos)}
        onClick={toggle}
        className={cn(
          'flex items-center rounded-full text-left transition-colors',
          collapsed ? 'size-10 justify-center' : 'h-11 min-w-0 flex-1 gap-2.5 pr-3 pl-2',
          pos || active ? 'bg-brand-soft' : 'hover:bg-canvas',
        )}
      >
        <UserAvatar name={account.name} />
        {collapsed ? null : (
          <span className="min-w-0">
            <span className="text-fg block truncate text-[13px] font-medium">{account.name}</span>
            <span className="text-faint block truncate text-[11.5px]">
              {today ?? '...'} today, {account.instances.valid} instance
              {account.instances.valid === 1 ? '' : 's'}
            </span>
          </span>
        )}
      </button>
      {pos
        ? createPortal(
            <div
              ref={menu}
              role="menu"
              style={{ left: pos.left, bottom: pos.bottom, width: MENU_WIDTH }}
              className="border-line-strong/70 animate-pop fixed z-[200] rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
            >
              <Menu account={account} onClose={close} />
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
