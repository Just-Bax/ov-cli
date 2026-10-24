import { LinkBreak as LinkSlashIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { ModelInfo, OpenAIAccount, ProviderAccount } from '@shared/types.ts'
import { ProviderBubble } from '@/components/common/ProviderLogo'
import { reportError } from '@/components/common/Toasts'
import { Button, Input, Label, SWITCH_TRACK, SwitchKnob } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatTokens } from '@/lib/cost'
import { forgetModels, useModels } from '@/lib/models'
import { PlanRow, type ProviderUi } from './parts'

const PROVIDER = 'openai'
const BASE_URL_EXAMPLE = 'http://gpu-box:8000/v1'

function openaiOf(account: ProviderAccount): OpenAIAccount {
  return account as OpenAIAccount
}

function OpenAIConnect({ onRefresh }: { account: ProviderAccount; onRefresh: () => void }) {
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const connect = async () => {
    setBusy(true)
    setError(undefined)
    try {
      await api.openaiConnect(baseUrl, apiKey)
      forgetModels(PROVIDER)
      onRefresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="bg-raised space-y-3 rounded-2xl px-4 py-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (baseUrl.trim() && !busy) void connect()
      }}
    >
      <div className="text-muted text-[12.5px] leading-relaxed">
        Your vLLM server, started with <code>--enable-auto-tool-choice</code> and a{' '}
        <code>--tool-call-parser</code>. Any other server with the same chat completions API and
        tool calls works too.
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label>Base URL</Label>
          <Input
            value={baseUrl}
            placeholder={BASE_URL_EXAMPLE}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>
        <div>
          <Label>API key</Label>
          <Input
            type="password"
            value={apiKey}
            placeholder="Optional"
            autoComplete="off"
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" size="sm" busy={busy} disabled={!baseUrl.trim()}>
          Connect
        </Button>
        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    </form>
  )
}

function OpenAIPlan() {
  return (
    <PlanRow title="vLLM" action={null}>
      Your own server, so nothing is billed here. Usage is counted in tokens.
    </PlanRow>
  )
}

function Disconnect({ account, onChange }: { account: ProviderAccount; onChange: () => void }) {
  if (!openaiOf(account).signedIn) return null

  const disconnect = async () => {
    await api.openaiDisconnect()
    forgetModels(PROVIDER)
    onChange()
  }

  return (
    <Button size="sm" variant="danger" onClick={() => void disconnect().catch(reportError)}>
      <LinkSlashIcon className="size-3.5" /> Disconnect
    </Button>
  )
}

function ModelRow({ model }: { model: ModelInfo }) {
  const [typed, setTyped] = useState(String(model.contextWindow ?? ''))
  const [busy, setBusy] = useState(false)

  const save = async (vision: boolean, contextWindow: string) => {
    setBusy(true)
    try {
      await api.openaiConfigureModel(model.id, vision, contextWindow ? Number(contextWindow) : null)
      forgetModels(PROVIDER)
    } catch (e) {
      reportError(e)
      setTyped(String(model.contextWindow ?? ''))
    } finally {
      setBusy(false)
    }
  }

  const reported = model.reportedWindow
    ? `Server says ${formatTokens(model.reportedWindow)}`
    : 'Server does not say'

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
      <div className="min-w-[200px] flex-1">
        <div className="text-fg truncate text-[13px] font-medium">{model.id}</div>
        <div className="text-muted text-[11.5px]">{reported}</div>
      </div>
      <div className="flex shrink-0 items-center gap-6">
        <label className="text-muted flex items-center gap-2 text-[12px] whitespace-nowrap">
          Context window
          <span className="w-28">
            <Input
              className="h-8 tabular-nums"
              inputMode="numeric"
              value={typed}
              disabled={busy}
              placeholder="tokens"
              onChange={(e) => setTyped(e.target.value.replace(/\D/g, ''))}
              onBlur={() => {
                if (typed !== String(model.contextWindow ?? '')) void save(model.vision, typed)
              }}
            />
          </span>
        </label>
        <label className="text-muted flex items-center gap-2 text-[12px] whitespace-nowrap">
          Sees images
          <button
            type="button"
            role="switch"
            aria-checked={model.vision}
            disabled={busy}
            onClick={() => void save(!model.vision, typed)}
            className={cn(SWITCH_TRACK, model.vision ? 'bg-brand' : 'bg-line-strong')}
          >
            <SwitchKnob on={model.vision} />
          </button>
        </label>
      </div>
    </div>
  )
}

function OpenAIModels() {
  const models = useModels(PROVIDER)
  if (!models) return null

  return (
    <div className="divide-line divide-y">
      <div className="px-5 pt-4 pb-2">
        <div className="text-fg text-[13.5px] font-medium">Served models</div>
        <div className="text-muted mt-0.5 text-[12px] leading-relaxed">
          The server cannot say whether a model reads images, so turn that on yourself. Set the
          context window when the server does not report it, or to use less than it allows.
        </div>
      </div>
      {models.map((m) => (
        <ModelRow key={`${m.id}:${m.vision}:${m.contextWindow}`} model={m} />
      ))}
    </div>
  )
}

export const OPENAI_UI: ProviderUi = {
  usageTitle: 'Tokens processed',
  usageNote:
    'Every step sends the whole conversation to your server again, so input adds up across requests. Nothing is billed.',
  usageHint: (tokens) =>
    tokens.cache_read
      ? undefined
      : 'Your server reported no cached tokens. Start vLLM with --enable-prompt-tokens-details to see how much of each request its prefix cache served.',
  accountBadge: <ProviderBubble provider={PROVIDER} className="size-10" />,
  summary: (account) => {
    const { signedIn, baseUrl } = openaiOf(account)
    return signedIn ? `Your server at ${baseUrl}, counted in tokens.` : 'No server connected.'
  },
  sidebar: (account) => {
    const { baseUrl } = openaiOf(account)
    return { detail: baseUrl ? new URL(baseUrl).host : 'Not connected' }
  },
  accountDetail: (account, runsAgent) => {
    const { signedIn, baseUrl, hasKey } = openaiOf(account)
    if (!signedIn) return 'Not connected'
    return `Connected to ${baseUrl}${hasKey ? ' with an API key' : ''}.${runsAgent ? ' Runs the agent.' : ''}`
  },
  SignIn: OpenAIConnect,
  Plan: OpenAIPlan,
  AccountAction: Disconnect,
  Models: OpenAIModels,
}
