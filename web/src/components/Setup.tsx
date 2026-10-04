import { ArrowRight, Check, ExternalLink, Server, SlidersHorizontal } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import type { ModelInfo, Status } from '@shared/types.ts'
import { defaultInstance, useInstances } from '@/components/InstancePicker'
import { Button, CopyButton, GithubMark, Input, Label, Select, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

function StepRow({
  n,
  done,
  active,
  icon,
  title,
  subtitle,
  children,
}: {
  n: number
  done: boolean
  active: boolean
  icon: ReactNode
  title: string
  subtitle: string
  children?: ReactNode
}) {
  return (
    <div
      className={cn(
        'border-line border-b px-5 py-4 last:border-b-0',
        !active && !done && 'opacity-50',
      )}
    >
      <div className="flex items-center gap-3">
        <div
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-full',
            done
              ? 'bg-ok-soft text-ok'
              : active
                ? 'bg-brand-soft text-brand-strong'
                : 'bg-canvas text-faint',
          )}
        >
          {done ? <Check className="size-4" /> : icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13.5px] font-semibold">
            <span className="text-faint mr-1 font-normal">{n}.</span>
            {title}
          </div>
          <div className="text-muted text-[12px]">{subtitle}</div>
        </div>
      </div>
      {active && children ? <div className="mt-3 pl-11">{children}</div> : null}
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
          <ExternalLink className="size-3.5" /> Open GitHub
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
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const signIn = async () => {
    setBusy(true)
    setError(undefined)
    const res = await api
      .loginInstance(url.trim())
      .catch((e: Error) => ({ ok: false, message: e.message }))
    setBusy(false)
    if (res.ok) onDone()
    else setError(res.message || 'Sign-in failed.')
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (url.trim()) void signIn()
      }}
    >
      <div className="flex gap-2">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="yours.onevizion.com"
          disabled={busy}
        />
        <Button type="submit" variant="primary" disabled={!url.trim() || busy}>
          {busy ? <Spinner className="size-3.5" /> : null}
          {busy ? 'Finish in the browser...' : 'Sign in'}
        </Button>
      </div>
      <div className="text-muted mt-1.5 text-[12px]">
        A browser window opens on the instance's own login page. Same as `ov login`.
      </div>
      {error ? <div className="text-danger mt-2 text-[12px]">{error}</div> : null}
    </form>
  )
}

export function Setup({ status, onDone }: { status: Status; onDone: () => void }) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState(status.settings.defaultModel)
  const { instances } = useInstances()
  const [instance, setInstance] = useState(status.settings.defaultInstance)
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
  useEffect(() => {
    if (instances && !instance) setInstance(defaultInstance(instances, ''))
  }, [instances])

  const current = !copilotOk ? 1 : !instancesOk ? 2 : 3

  return (
    <div className="flex min-h-full items-start justify-center px-6 py-14">
      <div className="w-full max-w-[600px]">
        <div className="text-fg mb-1 text-[20px] font-semibold">OV Agent setup</div>
        <p className="text-muted mb-6 text-[13px]">
          Three steps before the first run. Everything stays on this machine ({status.ov.version}).
        </p>

        <div className="bg-panel overflow-hidden rounded-2xl shadow-[var(--shadow-medium)]">
          <StepRow
            n={1}
            done={copilotOk}
            active={current === 1}
            icon={<GithubMark className="size-4" />}
            title="GitHub Copilot"
            subtitle={copilotOk ? `Signed in as ${status.copilot.user}` : 'Runs the agent'}
          >
            <CopilotSignIn onDone={onDone} />
          </StepRow>
          <StepRow
            n={2}
            done={instancesOk}
            active={current === 2}
            icon={<Server className="size-4" />}
            title="A OneVizion instance"
            subtitle={
              instancesOk
                ? `${status.instances.total} signed in`
                : 'Where the agent reads (and, if you allow it, changes) data'
            }
          >
            <InstanceSignIn onDone={onDone} />
          </StepRow>
          <StepRow
            n={3}
            done={false}
            active={current === 3}
            icon={<SlidersHorizontal className="size-4" />}
            title="Defaults"
            subtitle="Model and instance for new runs; both can be changed per run"
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
              <div>
                <Label>Default instance</Label>
                <Select
                  className="w-full"
                  value={instance}
                  onChange={setInstance}
                  placeholder="The current ov instance"
                  options={(instances ?? []).map((i) => ({ value: i.alias, label: i.alias }))}
                />
              </div>
              <div>
                <Button
                  variant="primary"
                  disabled={!model || saving}
                  onClick={async () => {
                    setSaving(true)
                    await api.saveSettings({ defaultModel: model, defaultInstance: instance })
                    setSaving(false)
                    onDone()
                  }}
                >
                  {saving ? <Spinner className="size-3.5" /> : null} Continue{' '}
                  <ArrowRight className="size-4" />
                </Button>
              </div>
            </div>
          </StepRow>
        </div>
      </div>
    </div>
  )
}
