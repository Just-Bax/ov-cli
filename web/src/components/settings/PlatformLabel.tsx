import type { Instance } from '@shared/types.ts'
import { editionLabel } from '@/lib/instances'

export function PlatformLabel({ instance }: { instance: Instance }) {
  const { access } = instance
  const platform = [editionLabel(access), access.version].filter(Boolean).join(' ')
  if (!platform || access.checking || access.error) return null

  return (
    <span title={platform} className="text-faint min-w-0 shrink truncate text-[11.5px]">
      {platform}
    </span>
  )
}
