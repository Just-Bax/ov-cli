import {
  SlidersHorizontal as AdjustmentsHorizontalIcon,
  ArrowRight as ArrowRightIcon,
  Check as CheckIcon,
  HardDrives as ServerIcon,
  User as UserIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useState } from 'react'
import type { ModelInfo, Provider, Status } from '@shared/types.ts'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { ProviderLogo } from '@/components/common/ProviderLogo'
import { providerReady, providerSummary } from '@/components/providers'
import { ProviderSelect, ProviderSetup } from '@/components/settings/Providers'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'
import { AddInstanceForm, SignInModal, type SignInTarget } from '@/components/signin/SignInModal'
import { reportError } from '@/components/common/Toasts'
import { Button, Card, Input, Label, Select, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { loadModels } from '@/lib/models'
import { plural } from '@/lib/text'

const STEPS = [1, 2, 3, 4]

function choices(names: string[]): string {
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} or ${names.at(-1)}` : names.join('')
}

function Step({
  n,
  done,
  active,
  last,
  icon,
  title,
  subtitle,
  action,
  children,
}: {
  n: number
  done: boolean
  active: boolean
  last?: boolean
  icon: ReactNode
  title: string
  subtitle: ReactNode
  action?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="relative flex gap-4 pb-7 last:pb-0">
      {!last ? (
        <span
          className={cn(
            'absolute top-12 bottom-1.5 left-[19px] w-0.5 rounded-full',
            done ? 'bg-ok/40' : 'bg-line',
          )}
        />
      ) : null}
      <span
        className={cn(
          'relative flex size-10 shrink-0 items-center justify-center rounded-full transition-colors',
          done
            ? 'bg-ok-soft text-ok'
            : active
              ? 'bg-brand text-white shadow-[0_4px_14px_rgba(66,165,245,0.35)]'
              : 'bg-raised text-faint',
        )}
      >
        {done ? <CheckIcon className="size-5" /> : icon}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-faint text-[11.5px] font-medium">Step {n}</div>
            <div
              className={cn('text-[14px] font-semibold', done || active ? 'text-fg' : 'text-muted')}
            >
              {title}
            </div>
            <div className="text-muted mt-0.5 text-[12.5px] leading-relaxed">{subtitle}</div>
          </div>
          {action}
        </div>
        {children ? <div className="mt-4">{children}</div> : null}
      </div>
    </div>
  )
}

function pickModel(models: ModelInfo[]): string {
  if (models.some((m) => m.id === 'opus')) return 'opus'
  const version = (id: string) => Number(/(\d+(?:\.\d+)?)/.exec(id)?.[1] ?? 0)
  const opus = models
    .filter((m) => /claude-opus/.test(m.id) && !/fast/.test(m.id))
    .sort((a, b) => version(b.id) - version(a.id))
  return (opus[0] ?? models[0])?.id ?? ''
}

function NameForm({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const trimmed = name.trim()

  const save = async () => {
    setSaving(true)
    try {
      await api.saveSettings({ fullName: trimmed })
      onSaved()
    } catch (e) {
      reportError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (trimmed) void save()
      }}
    >
      <Input
        aria-label="Full name"
        autoFocus
        className="min-w-0 flex-1"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Your full name"
      />
      <Button type="submit" variant="primary" busy={saving} disabled={!trimmed || saving}>
        Continue
      </Button>
    </form>
  )
}

function InstanceSignIn({ onDone }: { onDone: () => void }) {
  const [target, setTarget] = useState<SignInTarget>()
  const [pending, setPending] = useState(false)

  return (
    <div>
      <AddInstanceForm onSubmit={setTarget} />
      <div className="text-muted mt-2 px-1 text-[12px]">
        A browser window opens on the instance's login page. Leave the tenant empty to use your own.
      </div>
      <SignInModal
        target={target}
        pending={pending}
        onClose={() => setTarget(undefined)}
        onStart={() => setPending(true)}
        onFinished={(_, ok) => {
          setPending(false)
          if (ok) onDone()
        }}
      />
    </div>
  )
}

export function Setup({
  status: saved,
  onDone,
  onFinish,
}: {
  status: Status
  onDone: () => void
  onFinish: () => void
}) {
  const [models, setModels] = useState<ModelInfo[]>()
  const [model, setModel] = useState(saved.settings.defaultModel)
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  const [pending, setPending] = useState<Provider>()
  const status = pending ? { ...saved, provider: pending } : saved

  const nameOk = Boolean(status.settings.fullName.trim())
  const providerOk = providerReady(status)
  const instancesOk = status.instances.total > 0

  useEffect(() => {
    if (!nameOk || !providerOk) return

    loadModels(status.provider)
      .then((m) => {
        setModels(m)
        if (!model || !m.some((x) => x.id === model)) setModel(pickModel(m))
      })
      .catch(reportError)
  }, [nameOk, providerOk, status.provider])

  const pickProvider = (provider: Provider) => {
    if (provider === status.provider) return
    setPending(provider)
    api
      .saveSettings({ provider })
      .then(onDone, reportError)
      .finally(() => setPending(undefined))
  }

  useEffect(() => setAdding(false), [status.instances.total])

  const current = !nameOk ? 1 : !providerOk ? 2 : !instancesOk ? 3 : 4

  const finish = async () => {
    setSaving(true)
    try {
      await api.saveSettings({ defaultModel: model })
      onDone()
      onFinish()
    } catch (e) {
      reportError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative h-full scrollbar-thin overflow-y-auto bg-white">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_60%_60%_at_50%_0%,#e1f5fe_0%,transparent_70%)]" />
      <main className="relative mx-auto flex max-w-[560px] flex-col items-center px-6 pt-16 pb-16 text-center">
        <img src={wordmark} alt="OV Agent" className="h-[34px] w-auto" />
        <h1 className="text-fg mt-10 text-[30px] leading-tight font-semibold tracking-tight">
          Set up OV Agent
        </h1>
        <p className="text-muted mt-2 text-[14px] leading-relaxed">
          Ask about OneVizion instances, investigate problems and cases, and change configuration
          and data with an agent that reads the instances for you. Everything stays on this
          computer.
        </p>

        <Card className="mt-10 w-full p-7 text-left shadow-[0_12px_40px_rgba(38,50,56,0.08)]">
          <div className="flex items-baseline gap-2">
            <div className="text-fg text-[18px] font-semibold">Get started</div>
            <div className="text-faint ml-auto text-[12px]">
              Step {current} of {STEPS.length}
            </div>
          </div>
          <div className="mt-4 grid grid-cols-4 gap-1.5">
            {STEPS.map((n) => (
              <span
                key={n}
                className={cn(
                  'h-1.5 rounded-full transition-colors duration-(--duration-medium)',
                  n < current ? 'bg-ok' : n === current ? 'bg-brand' : 'bg-raised',
                )}
              />
            ))}
          </div>

          <div className="mt-7">
            <Step
              n={1}
              done={nameOk}
              active={current === 1}
              icon={<UserIcon className="size-5" />}
              title="Tell us your name"
              subtitle={
                nameOk
                  ? `Hi, ${status.settings.fullName}.`
                  : 'Shown on your account and given to the agent, so it knows who it works for.'
              }
            >
              {current === 1 ? <NameForm onSaved={onDone} /> : null}
            </Step>
            <Step
              n={2}
              done={providerOk}
              active={current === 2}
              icon={<ProviderLogo provider={status.provider} className="size-5" />}
              title="Pick who runs the agent"
              subtitle={
                providerOk
                  ? `${PROVIDER_BRANDS[status.provider].name} runs the agent.`
                  : `${choices(status.providers.map((p) => PROVIDER_BRANDS[p.id].name))}.`
              }
            >
              {current === 2 ? (
                <div className="space-y-3">
                  <ProviderSelect
                    className="w-[260px]"
                    providers={status.providers}
                    value={status.provider}
                    onChange={pickProvider}
                  />
                  <div className="text-muted text-[12px]">{providerSummary(status)}</div>
                  <ProviderSetup status={status} onRefresh={onDone} />
                </div>
              ) : null}
            </Step>
            <Step
              n={3}
              done={instancesOk}
              active={current === 3}
              icon={<ServerIcon className="size-5" />}
              title="Add a OneVizion instance"
              subtitle={
                instancesOk
                  ? `${plural(status.instances.total, 'instance')} signed in.`
                  : 'Where the agent reads data, with your own account and permissions.'
              }
              action={
                instancesOk && providerOk ? (
                  <Button size="sm" variant="ghost" onClick={() => setAdding((a) => !a)}>
                    {adding ? 'Cancel' : 'Add another'}
                  </Button>
                ) : null
              }
            >
              {current === 3 || adding ? <InstanceSignIn onDone={onDone} /> : null}
            </Step>
            <Step
              n={4}
              last
              done={false}
              active={current === 4}
              icon={<AdjustmentsHorizontalIcon className="size-5" />}
              title="Pick a model"
              subtitle="The default for new threads. You can switch it for any thread."
            >
              {current === 4 ? (
                <div className="grid gap-4">
                  <div>
                    <Label>Default model</Label>
                    {models ? (
                      <Select
                        className="w-full"
                        value={model}
                        onChange={setModel}
                        placeholder="Pick a model"
                        options={models.map((m) => ({ value: m.id, label: m.name }))}
                      />
                    ) : (
                      <Skeleton className="h-9 w-full rounded-full" />
                    )}
                  </div>
                  <Button
                    variant="primary"
                    size="lg"
                    busy={saving}
                    disabled={!model || saving}
                    onClick={() => void finish()}
                  >
                    Start using OV Agent
                    <ArrowRightIcon className="size-4" />
                  </Button>
                </div>
              ) : null}
            </Step>
          </div>
        </Card>
        <div className="text-faint mt-6 text-[12px]">{status.ov.version}</div>
      </main>
    </div>
  )
}
