import {
  AdjustmentsHorizontalIcon,
  ArrowRightIcon,
  ArrowTopRightOnSquareIcon,
  CheckIcon,
  ServerIcon,
} from '@heroicons/react/24/outline'
import { type ReactNode, useEffect, useState } from 'react'
import type { ModelInfo, Status } from '@shared/types.ts'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { AddInstanceForm, SignInModal, type SignInTarget } from '@/components/SignInModal'
import { Button, Card, CopyButton, GithubMark, Label, Select, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

function Step({
  n,
  done,
  active,
  last,
  icon,
  title,
  subtitle,
  children,
}: {
  n: number
  done: boolean
  active: boolean
  last?: boolean
  icon: ReactNode
  title: string
  subtitle: string
  children?: ReactNode
}) {
  return (
    <div className="relative flex gap-4 pb-6 last:pb-0">
      {!last ? (
        <span
          className={cn(
            'absolute top-10 bottom-1 left-[19px] w-0.5 rounded-full',
            done ? 'bg-ok/40' : 'bg-line',
          )}
        />
      ) : null}
      <span
        className={cn(
          'relative flex size-10 shrink-0 items-center justify-center rounded-full',
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
        <div className="text-faint text-[11.5px] font-medium">Step {n}</div>
        <div className={cn('text-[14px] font-semibold', done || active ? 'text-fg' : 'text-muted')}>
          {title}
        </div>
        <div className="text-muted mt-0.5 text-[12.5px] leading-relaxed">{subtitle}</div>
        {active && children ? <div className="mt-3.5">{children}</div> : null}
      </div>
    </div>
  )
}

function CopilotSignIn({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState<{ userCode: string; verificationUri: string }>()
  const [error, setError] = useState<string>()

  const start = async () => {
    setError(undefined)
    try {
      const flow = await api.deviceStart()
      setCode(flow)
      let interval = flow.interval * 1000
      for (;;) {
        await new Promise((r) => setTimeout(r, interval))
        const res = await api.devicePoll(flow.deviceCode)
        if (res.status === 'ok') return onDone()
        if (res.status === 'slow_down') interval += 5000
        if (res.status === 'error') throw new Error(res.message)
      }
    } catch (e) {
      setError((e as Error).message)
      setCode(undefined)
    }
  }

  if (!code) {
    return (
      <div>
        <Button variant="primary" onClick={start}>
          <GithubMark className="size-3.5" /> Sign in with GitHub
        </Button>
        {error ? <div className="text-danger mt-2 text-[12px]">{error}</div> : null}
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="bg-canvas rounded-full px-4 py-1.5 font-mono text-lg font-semibold tracking-[0.2em]">
        {code.userCode}
      </div>
      <CopyButton text={code.userCode} label="Copy code" />
      <a href={code.verificationUri} target="_blank" rel="noreferrer">
        <Button size="sm" variant="primary">
          <ArrowTopRightOnSquareIcon className="size-3.5" /> Open GitHub
        </Button>
      </a>
      <span className="text-muted flex items-center gap-1.5 text-[12px]">
        <Spinner className="text-brand size-3.5" /> Waiting for approval
      </span>
    </div>
  )
}

function pickModel(models: ModelInfo[]): string {
  const version = (id: string) => Number(/(\d+(?:\.\d+)?)/.exec(id)?.[1] ?? 0)
  const opus = models
    .filter((m) => /claude-opus/.test(m.id) && !/fast/.test(m.id))
    .sort((a, b) => version(b.id) - version(a.id))
  return (opus[0] ?? models[0])?.id ?? ''
}

function InstanceSignIn({ onDone }: { onDone: () => void }) {
  const [target, setTarget] = useState<SignInTarget>()
  const [pending, setPending] = useState(false)
  return (
    <div>
      <AddInstanceForm onSubmit={setTarget} />
      <div className="text-muted mt-1.5 text-[12px]">Leave the tenant empty to use your own.</div>
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

export function Setup({ status, onDone }: { status: Status; onDone: () => void }) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState(status.settings.defaultModel)
  const [saving, setSaving] = useState(false)

  const copilotOk = status.copilot.signedIn
  const instancesOk = status.instances.total > 0

  useEffect(() => {
    if (!copilotOk) return
    api
      .models()
      .then((m) => {
        setModels(m)
        if (!model) setModel(pickModel(m))
      })
      .catch(() => undefined)
  }, [copilotOk])

  const current = !copilotOk ? 1 : !instancesOk ? 2 : 3
  const done = Number(copilotOk) + Number(instancesOk)

  return (
    <div className="relative h-full scrollbar-thin overflow-y-auto bg-white">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_60%_60%_at_50%_0%,#e1f5fe_0%,transparent_70%)]" />
      <main className="relative mx-auto flex max-w-[520px] flex-col items-center px-6 pt-16 pb-16 text-center">
        <img src={wordmark} alt="OV Agent" className="h-[34px] w-auto" />
        <h1 className="text-fg mt-10 text-[30px] leading-tight font-semibold tracking-tight">
          Set up OV Agent
        </h1>
        <p className="text-muted mt-2 text-[14px] leading-relaxed">
          Troubleshoot OneVizion cases with an agent that reads the case, the instance and the code
          for you. Everything stays on this computer.
        </p>
        <div className="mt-10 w-full">
          <Card className="p-6 text-left shadow-[0_12px_40px_rgba(38,50,56,0.08)]">
            <div className="flex items-baseline gap-2">
              <div className="text-fg text-[18px] font-semibold">Get started</div>
              <div className="text-faint ml-auto text-[12px]">{done} of 3 done</div>
            </div>
            <div className="text-muted mt-1 text-[13px]">Three steps, about two minutes.</div>
            <div className="bg-raised mt-4 h-1.5 overflow-hidden rounded-full">
              <div
                className="bg-brand h-full rounded-full transition-[width] duration-500"
                style={{ width: `${Math.max(6, (done / 3) * 100)}%` }}
              />
            </div>

            <div className="mt-6">
              <Step
                n={1}
                done={copilotOk}
                active={current === 1}
                icon={<GithubMark className="size-5" />}
                title="Sign in to GitHub Copilot"
                subtitle={
                  copilotOk
                    ? `Signed in as ${status.copilot.user}.`
                    : 'Copilot runs the agent. You approve this computer once on GitHub.'
                }
              >
                <CopilotSignIn onDone={onDone} />
              </Step>
              <Step
                n={2}
                done={instancesOk}
                active={current === 2}
                icon={<ServerIcon className="size-5" />}
                title="Add a OneVizion instance"
                subtitle={
                  instancesOk
                    ? `${status.instances.total} instance${status.instances.total === 1 ? '' : 's'} signed in.`
                    : "Where the agent reads data. It signs in through the instance's own login page."
                }
              >
                <InstanceSignIn onDone={onDone} />
              </Step>
              <Step
                n={3}
                last
                done={false}
                active={current === 3}
                icon={<AdjustmentsHorizontalIcon className="size-5" />}
                title="Pick a model"
                subtitle="The default for new runs. You can switch it for any run."
              >
                <div className="grid gap-3">
                  <div>
                    <Label>Default model</Label>
                    <Select
                      className="w-full"
                      value={model}
                      onChange={setModel}
                      placeholder={models.length ? 'Pick a model' : 'Loading models...'}
                      options={models.map((m) => ({ value: m.id, label: m.name }))}
                    />
                  </div>
                  <Button
                    variant="primary"
                    size="lg"
                    disabled={!model || saving}
                    onClick={async () => {
                      setSaving(true)
                      await api.saveSettings({ defaultModel: model })
                      setSaving(false)
                      onDone()
                    }}
                  >
                    {saving ? <Spinner className="size-4" /> : null} Start using OV Agent
                    <ArrowRightIcon className="size-4" />
                  </Button>
                </div>
              </Step>
            </div>
          </Card>
        </div>
        <div className="text-faint mt-6 text-[12px]">{status.ov.version}</div>
      </main>
    </div>
  )
}
