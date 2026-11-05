import { Check as CheckIcon, Copy as Square2StackIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { DatadogArea, DatadogStatus } from '@shared/types.ts'
import datadogMark from '@/assets/datadog.svg'
import { DatadogInstanceMatches } from '@/components/integrations/DatadogMatches'
import { IconBadge, Select, useCopy } from '@/components/common/ui'
import {
  ConnectModal,
  type ConnectProps,
  IntegrationAccountRow,
  IntegrationCard,
  KeyField,
  useConnect,
} from '@/components/integrations/parts'
import { api } from '@/lib/api'
import { useLoad } from '@/lib/hooks'

export const DATADOG_PURPLE = '#632CA6'
const DEFAULT_SITE = 'datadoghq.com'
const DEFAULT_APP_HOST = 'app.datadoghq.com'

const AREA_LABELS: Record<DatadogArea, string> = {
  logs: 'Logs',
  metrics: 'Metrics',
  monitors: 'Monitors',
  events: 'Events',
  apm: 'APM',
  hosts: 'Hosts',
}

function siteAddress(status: DatadogStatus): string {
  return status.sites.find((s) => s.id === status.site)?.app ?? status.site
}

export function DatadogBadge({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <IconBadge size={size} color={DATADOG_PURPLE}>
      <img src={datadogMark} alt="Datadog" className={size === 'lg' ? 'size-7' : 'size-6'} />
    </IconBadge>
  )
}

export function useDatadog() {
  const { value: status, setValue: setStatus } = useLoad(api.datadog, [])
  return { status, setStatus }
}

function ScopesHint({ scopes }: { scopes: string[] }) {
  const [copied, copy] = useCopy()

  return (
    <div className="bg-raised rounded-2xl px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="text-fg text-[12.5px] font-medium">
          Read-only scopes for the application key
        </span>
        <button
          type="button"
          onClick={() => copy(scopes.join(' '))}
          className="text-brand-strong hover:bg-brand-soft ml-auto inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px] font-medium"
        >
          {copied ? <CheckIcon className="size-3" /> : <Square2StackIcon className="size-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {scopes.map((s) => (
          <span
            key={s}
            className="text-text inline-flex h-6 items-center rounded-full bg-white px-2.5 font-mono text-[11px]"
          >
            {s}
          </span>
        ))}
      </div>
      <div className="text-muted mt-2 text-[11.5px] leading-relaxed">
        Pick only these when creating the key. Anything left out is skipped, never an error.
      </div>
    </div>
  )
}

export function DatadogConnectModal({
  open,
  status,
  onClose,
  onConnected,
}: ConnectProps<DatadogStatus>) {
  const [site, setSite] = useState(status?.site ?? DEFAULT_SITE)
  const [apiKey, setApiKey] = useState('')
  const [appKey, setAppKey] = useState('')
  const { busy, error, setError, submit } = useConnect(
    () => api.datadogConnect(site, apiKey, appKey),
    onConnected,
  )

  useEffect(() => {
    if (!open) return
    setSite(status?.site ?? DEFAULT_SITE)
    setApiKey('')
    setAppKey('')
    setError(undefined)
  }, [open])

  const app = `https://${status?.sites.find((s) => s.id === site)?.app ?? DEFAULT_APP_HOST}`

  return (
    <ConnectModal
      open={open}
      busy={busy}
      badge={<DatadogBadge />}
      title="Connect Datadog"
      subtitle="Logs, metrics, monitors and events for your instances, read-only."
      error={error}
      busyLabel="Checking keys"
      ready={Boolean(apiKey.trim() && appKey.trim())}
      onClose={onClose}
      onSubmit={() => void submit()}
      privacy="Keys stay in this computer's credential store and are only sent to Datadog. Your Datadog admins can see application keys and may audit their use. Logs the agent reads in a thread are sent to the provider that runs the agent, like any other tool result."
    >
      <div>
        <div className="text-fg text-[13px] font-medium">Site</div>
        <Select
          className="mt-1.5 w-full"
          value={site}
          onChange={setSite}
          options={(status?.sites ?? []).map((s) => ({
            value: s.id,
            label: s.app,
            hint: s.id === DEFAULT_SITE ? 'Most accounts' : undefined,
          }))}
        />
        <div className="text-muted mt-1.5 px-1 text-[11.5px]">
          The address in your browser when you use Datadog. Most accounts use app.datadoghq.com.
        </div>
      </div>

      <KeyField
        label="API key"
        href={`${app}/organization-settings/api-keys`}
        linkLabel="Open API keys"
        value={apiKey}
        onChange={setApiKey}
        placeholder="32 characters"
        hint="Organization Settings > API Keys. Copy an existing key, or ask an admin for one. On its own it cannot read data."
      />
      <KeyField
        label="Application key"
        href={`${app}/personal-settings/application-keys`}
        linkLabel="Open application keys"
        value={appKey}
        onChange={setAppKey}
        placeholder="40 characters"
        hint="Personal Settings > Application Keys > New Key. It reads with your own permissions."
      />

      <ScopesHint scopes={status?.scopes ?? []} />
    </ConnectModal>
  )
}

function renderConnect(props: ConnectProps<DatadogStatus>) {
  return <DatadogConnectModal {...props} />
}

export function DatadogCard({
  status,
  setStatus,
}: {
  status?: DatadogStatus
  setStatus: (s: DatadogStatus) => void
}) {
  return (
    <IntegrationCard
      name="Datadog"
      badge={<DatadogBadge />}
      status={status}
      setStatus={setStatus}
      connectedDetail={siteAddress}
      idleDetail="Logs, metrics, monitors, events and APM for your instances."
      changeLabel="Change keys"
      areas={AREA_LABELS}
      keysTitle={(s) => `API key ...${s.apiKeyLast4}, application key ...${s.appKeyLast4}`}
      test={api.datadogTest}
      footer={(s) => (
        <div className="border-line border-t">
          <DatadogInstanceMatches status={s} onSaved={setStatus} />
        </div>
      )}
      renderConnect={renderConnect}
    />
  )
}

export function DatadogAccountRow({
  status,
  setStatus,
}: {
  status?: DatadogStatus
  setStatus: (s: DatadogStatus) => void
}) {
  return (
    <IntegrationAccountRow
      name="Datadog"
      badge={<DatadogBadge />}
      status={status}
      setStatus={setStatus}
      connectedDetail={(s) =>
        `Connected to ${siteAddress(s)} with keys ending ...${s.apiKeyLast4} and ...${s.appKeyLast4}`
      }
      disconnectBody="The keys are removed from this computer. Instance matches are kept for next time."
      disconnect={api.datadogDisconnect}
      renderConnect={renderConnect}
    />
  )
}
