import { useState } from 'react'
import type { CostTotal, Provider, RunCost } from '@shared/types.ts'
import { ProviderLogo } from '@/components/common/ProviderLogo'
import { reportError } from '@/components/common/Toasts'
import { Shimmer } from '@/components/common/ui'
import { PROVIDER_UI } from '@/components/providers'
import { api } from '@/lib/api'
import { formatAmount, formatCost, formatTokens, orderedTokens, tokenLabel } from '@/lib/cost'
import { modelName, useModels } from '@/lib/models'
import { providerStatus, useSettings } from '@/lib/settings'

export function CostPill({
  runId,
  provider,
  cost,
}: {
  runId: string
  provider: Provider
  cost?: CostTotal
}) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<RunCost>()
  const models = useModels(provider)
  const { providers } = useSettings()
  const unit = providerStatus(providers, provider).costUnit

  if (!cost) {
    return (
      <span
        title="Usage was not recorded for this thread"
        className="text-faint inline-flex h-8 items-center rounded-full px-3 text-[12px]"
      >
        Not tracked
      </span>
    )
  }

  const show = () => {
    setOpen(true)
    api.runCost(runId).then(setDetail, reportError)
  }

  return (
    <span className="relative" onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
      <span className="bg-raised text-text inline-flex h-8 cursor-default items-center gap-1.5 rounded-full px-3 text-[12px] font-medium tabular-nums">
        <ProviderLogo provider={provider} className="size-3.5" />
        {formatCost(cost, unit)}
      </span>
      {open ? (
        <div className="border-line animate-pop absolute top-full right-0 z-30 mt-1.5 w-[280px] rounded-2xl border bg-white p-3.5 text-[12px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]">
          <div className="text-fg flex items-baseline justify-between font-semibold">
            <span>{PROVIDER_UI[provider].usageTitle}</span>
            <span className="tabular-nums">{formatCost(cost, unit)}</span>
          </div>
          <div className="text-muted mt-0.5">
            {cost.requests} request{cost.requests === 1 ? '' : 's'}
          </div>
          {detail ? (
            <>
              <div className="border-line mt-3 space-y-1 border-t pt-3">
                {orderedTokens(detail.tokens).map(([kind, count]) => (
                  <div key={kind} className="flex justify-between">
                    <span className="text-muted">{tokenLabel(kind)}</span>
                    <span className="text-text tabular-nums">{formatTokens(count)} tokens</span>
                  </div>
                ))}
              </div>
              {detail.models.length > 1 ? (
                <div className="border-line mt-3 space-y-1 border-t pt-3">
                  {detail.models.map((m) => (
                    <div key={`${m.provider}:${m.model}`} className="flex justify-between gap-3">
                      <span className="text-muted truncate">{modelName(models, m.model)}</span>
                      <span className="text-text shrink-0 tabular-nums">
                        {formatAmount(m.amount, providerStatus(providers, m.provider).costUnit)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <div className="mt-3 text-center text-[12px]">
              <Shimmer>Loading costs</Shimmer>
            </div>
          )}
        </div>
      ) : null}
    </span>
  )
}
