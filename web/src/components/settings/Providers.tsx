import type { Provider, ProviderStatus, Status } from '@shared/types.ts'
import { ProviderLogo } from '@/components/common/ProviderLogo'
import { Select } from '@/components/common/ui'
import { currentProvider, PROVIDER_UI, providerReady } from '@/components/providers'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'

export function ProviderSelect({
  providers,
  value,
  onChange,
  className,
}: {
  providers: ProviderStatus[]
  value: Provider
  onChange: (provider: Provider) => void
  className?: string
}) {
  return (
    <Select
      className={className}
      value={value}
      onChange={(v) => onChange(v as Provider)}
      options={providers.map((p) => ({
        value: p.id,
        label: PROVIDER_BRANDS[p.id].name,
        icon: <ProviderLogo provider={p.id} className="size-4" />,
      }))}
    />
  )
}

export function ProviderSetup({ status, onRefresh }: { status: Status; onRefresh: () => void }) {
  if (providerReady(status)) return null
  const current = currentProvider(status)
  const { SignIn } = PROVIDER_UI[current.id]
  return <SignIn account={current.account} onRefresh={onRefresh} />
}
