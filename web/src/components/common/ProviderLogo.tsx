import type { Provider } from '@shared/types.ts'
import { cn } from '@/lib/cn'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'

export function ProviderLogo({ provider, className }: { provider: Provider; className?: string }) {
  const brand = PROVIDER_BRANDS[provider]

  return (
    <svg
      viewBox="0 0 24 24"
      aria-label={brand.name}
      role="img"
      className={cn('size-4 shrink-0', brand.color, className)}
      fill="currentColor"
    >
      {brand.marks.map((mark) => (
        <path key={mark.path} d={mark.path} className={mark.color} fill="currentColor" />
      ))}
    </svg>
  )
}

export function ProviderBubble({
  provider,
  className,
}: {
  provider: Provider
  className?: string
}) {
  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full',
        PROVIDER_BRANDS[provider].bubble,
        className,
      )}
    >
      <ProviderLogo provider={provider} className="size-[55%]" />
    </span>
  )
}
