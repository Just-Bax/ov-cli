import { useState } from 'react'
import type { ModelInfo, Provider, ProviderStatus, ReasoningLevel } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Card, Segmented, Select, Skeleton } from '@/components/common/ui'
import { PROVIDER_UI } from '@/components/providers'
import { ProviderSelect } from '@/components/settings/Providers'
import { Row } from '@/components/settings/Row'
import { cn } from '@/lib/cn'
import { useModels } from '@/lib/models'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'
import { providerStatus, useSettings } from '@/lib/settings'

const MODEL_FIELD = 'w-[260px]'

const REASONING: { value: ReasoningLevel | ''; label: string }[] = [
  { value: '', label: 'Auto' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'max', label: 'Max' },
]

function reasoningHint(levels: ReasoningLevel[] | undefined, wanted: ReasoningLevel | ''): string {
  const base = 'How long models think before answering. Higher is slower and costs more.'
  if (levels && !levels.length) return `${base} Your main model has no levels.`
  if (levels && wanted && !levels.includes(wanted))
    return `${base} Your main model uses the nearest one it has.`
  return base
}

function ModelSelect({
  models,
  value,
  placeholder,
  onChange,
}: {
  models: ModelInfo[] | undefined
  value: string
  placeholder: string
  onChange: (value: string) => void
}) {
  if (!models) return <Skeleton className={cn(MODEL_FIELD, 'h-9 rounded-full')} />

  return (
    <Select
      className={MODEL_FIELD}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      options={models.map((m) => ({ value: m.id, label: m.name }))}
    />
  )
}

function ModelRows({ provider, switching }: { provider: Provider; switching: boolean }) {
  const { settings, update } = useSettings()
  const loaded = useModels(provider)
  const models = switching ? undefined : loaded

  return (
    <>
      <Row title="Main model" hint="Used for every new thread. You can switch it for any thread.">
        <ModelSelect
          models={models}
          value={settings.defaultModel}
          placeholder="Pick a model"
          onChange={(v) => void update({ defaultModel: v })}
        />
      </Row>
      <Row
        title="Reasoning"
        hint={reasoningHint(
          models?.find((m) => m.id === settings.defaultModel)?.reasoning,
          settings.reasoning,
        )}
      >
        <Segmented
          label="Reasoning"
          value={settings.reasoning}
          options={REASONING}
          onChange={(v) => void update({ reasoning: v })}
        />
      </Row>
      <Row
        title="Fast model"
        hint="Writes thread titles, drives the browser and checks every command and change before it runs. Pick a quick, cheap model."
      >
        <ModelSelect
          models={models}
          value={settings.fastModel}
          placeholder="Pick a fast model"
          onChange={(v) => void update({ fastModel: v })}
        />
      </Row>
    </>
  )
}

function Connection({
  provider,
  switching,
  onChange,
}: {
  provider: ProviderStatus
  switching: boolean
  onChange: () => void
}) {
  const { SignIn, AccountAction, Models, accountDetail } = PROVIDER_UI[provider.id]

  if (!provider.account.signedIn)
    return (
      <div className="px-5 py-4">
        <SignIn account={provider.account} onRefresh={onChange} />
      </div>
    )

  return (
    <>
      <Row title="Account" hint={accountDetail(provider.account, false)}>
        {AccountAction ? <AccountAction account={provider.account} onChange={onChange} /> : null}
      </Row>
      {Models ? <Models /> : null}
      <ModelRows provider={provider.id} switching={switching} />
    </>
  )
}

export function ProviderSettings({ onChange }: { onChange: () => void }) {
  const { settings, providers, update } = useSettings()
  const [pending, setPending] = useState<Provider>()
  const shown = pending ?? settings.provider

  const pickProvider = (provider: Provider) => {
    if (provider === shown) return
    setPending(provider)
    update({ provider })
      .then(onChange, reportError)
      .finally(() => setPending(undefined))
  }

  return (
    <Card className="divide-line divide-y">
      <Row
        title="Provider"
        hint={
          pending
            ? `Switching to ${PROVIDER_BRANDS[pending].name}. New threads will use it; existing threads keep theirs.`
            : 'Who runs the agent. New threads use it; existing threads keep theirs.'
        }
      >
        <ProviderSelect
          className={MODEL_FIELD}
          providers={providers}
          value={shown}
          onChange={pickProvider}
        />
      </Row>
      <Connection
        key={shown}
        provider={providerStatus(providers, shown)}
        switching={Boolean(pending)}
        onChange={onChange}
      />
    </Card>
  )
}
