import { CpuChipIcon } from '@heroicons/react/24/outline'
import { useState } from 'react'
import type { CostTotal, RunCost } from '@shared/types.ts'
import { useModels } from '@/components/ModelPicker'
import { reportError } from '@/components/Toasts'
import { Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { formatCredits, formatTokens, orderedTokens, tokenLabel } from '@/lib/cost'

export function CostPill({ runId, cost }: { runId: string; cost?: CostTotal }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<RunCost>()
  const models = useModels()
  const name = (id: string) => models.find((m) => m.id === id)?.name ?? id

  if (!cost) {
    return (
      <span
        title="Usage was not recorded for this thread"
        className="text-faint inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12px]"
      >
        <CpuChipIcon className="size-4" />
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
        <CpuChipIcon className="text-muted size-4" />
        {formatCredits(cost.credits)} credits
      </span>
      {open ? (
        <div className="border-line animate-pop absolute top-full right-0 z-30 mt-1.5 w-[280px] rounded-2xl border bg-white p-3.5 text-[12px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]">
          <div className="text-fg flex items-baseline justify-between font-semibold">
            <span>Copilot usage</span>
            <span className="tabular-nums">{formatCredits(cost.credits)} credits</span>
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
                    <div key={m.model} className="flex justify-between gap-3">
                      <span className="text-muted truncate">{name(m.model)}</span>
                      <span className="text-text shrink-0 tabular-nums">
                        {formatCredits(m.credits)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <div className="mt-3 flex justify-center">
              <Spinner className="text-brand size-4" />
            </div>
          )}
        </div>
      ) : null}
    </span>
  )
}
