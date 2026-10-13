import {
  SlidersHorizontal as AdjustmentsHorizontalIcon,
  ArrowRight as ArrowRightIcon,
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  Check as CheckIcon,
  HardDrives as ServerIcon,
  Copy as Square2StackIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import type { ModelInfo, Status } from '@shared/types.ts'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { AddInstanceForm, SignInModal, type SignInTarget } from '@/components/signin/SignInModal'
import { reportError } from '@/components/common/Toasts'
import { Button, Card, GithubMark, Label, Select, Spinner, useCopy } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { SECOND_MS } from '@/lib/time'

const SLOW_DOWN_STEP_MS = 5000
const STEPS = [1, 2, 3]

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

function CopilotSignIn({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState<{ userCode: string; verificationUri: string }>()
  const [error, setError] = useState<string>()
  const [starting, setStarting] = useState(false)
  const [copied, copy] = useCopy()
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const poll = async (deviceCode: string, seconds: number) => {
    let interval = seconds * SECOND_MS
    while (mounted.current) {
      await new Promise((r) => setTimeout(r, interval))
      const res = await api.devicePoll(deviceCode)
      if (res.status === 'ok') return onDone()
      if (res.status === 'error') throw new Error(res.message)
      if (res.status === 'slow_down') interval += SLOW_DOWN_STEP_MS
    }
  }

  const start = async () => {
    setError(undefined)
    setStarting(true)
    try {
      const flow = await api.deviceStart()
      setCode(flow)
      setStarting(false)
      await poll(flow.deviceCode, flow.interval)
    } catch (e) {
      setError((e as Error).message)
      setCode(undefined)
      setStarting(false)
    }
  }

  if (!code)
    return (
      <div>
        <Button variant="primary" size="lg" disabled={starting} onClick={() => void start()}>
          {starting ? <Spinner className="size-4" /> : <GithubMark className="size-4" />} Sign in
          with GitHub
        </Button>
        {error ? <div className="text-danger mt-2 text-[12.5px]">{error}</div> : null}
      </div>
    )

  return (
    <div className="bg-raised rounded-2xl p-4">
      <div className="text-muted text-[12px]">Enter this code on GitHub</div>
      <div className="mt-1.5 flex items-center gap-2">
        <span className="text-fg font-mono text-[26px] font-semibold tracking-[0.16em] select-all">
          {code.userCode}
        </span>
        <button
          type="button"
          aria-label="Copy code"
          onClick={() => copy(code.userCode)}
          className={cn(
            'flex size-9 items-center justify-center rounded-full transition-colors',
            copied ? 'bg-ok-soft text-ok' : 'text-muted hover:text-fg bg-white',
          )}
        >
          {copied ? <CheckIcon className="size-4" /> : <Square2StackIcon className="size-4" />}
        </button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button
          variant="primary"
          onClick={() => {
            copy(code.userCode)
            window.open(code.verificationUri, '_blank', 'noopener')
          }}
        >
          Copy code and open GitHub <ArrowTopRightOnSquareIcon className="size-3.5" />
        </Button>
        <span className="text-muted inline-flex items-center gap-2 text-[12.5px]">
          <Spinner className="text-brand size-3.5" /> Waiting for you to approve
        </span>
      </div>
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
  status,
  onDone,
  onFinish,
}: {
  status: Status
  onDone: () => void
  onFinish: () => void
}) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState(status.settings.defaultModel)
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)

  const copilotOk = status.copilot.signedIn
  const instancesOk = status.instances.total > 0

  useEffect(() => {
    if (!copilotOk) return

    api
      .models()
      .then((m) => {
        setModels(m)
        if (!model || !m.some((x) => x.id === model)) setModel(pickModel(m))
      })
      .catch(reportError)
  }, [copilotOk])

  useEffect(() => setAdding(false), [status.instances.total])

  const current = !copilotOk ? 1 : !instancesOk ? 2 : 3

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
          Troubleshoot OneVizion cases with an agent that reads the case, the instance and the code
          for you. Everything stays on this computer.
        </p>

        <Card className="mt-10 w-full p-7 text-left shadow-[0_12px_40px_rgba(38,50,56,0.08)]">
          <div className="flex items-baseline gap-2">
            <div className="text-fg text-[18px] font-semibold">Get started</div>
            <div className="text-faint ml-auto text-[12px]">
              Step {current} of {STEPS.length}
            </div>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-1.5">
            {STEPS.map((n) => (
              <span
                key={n}
                className={cn(
                  'h-1.5 rounded-full transition-colors duration-500',
                  n < current ? 'bg-ok' : n === current ? 'bg-brand' : 'bg-raised',
                )}
              />
            ))}
          </div>

          <div className="mt-7">
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
              {current === 1 ? <CopilotSignIn onDone={onDone} /> : null}
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
                  : 'Where the agent reads data, with your own account and permissions.'
              }
              action={
                instancesOk && copilotOk ? (
                  <Button size="sm" variant="ghost" onClick={() => setAdding((a) => !a)}>
                    {adding ? 'Cancel' : 'Add another'}
                  </Button>
                ) : null
              }
            >
              {current === 2 || adding ? <InstanceSignIn onDone={onDone} /> : null}
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
              {current === 3 ? (
                <div className="grid gap-4">
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
                    onClick={() => void finish()}
                  >
                    {saving ? <Spinner className="size-4" /> : null} Start using OV Agent
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
