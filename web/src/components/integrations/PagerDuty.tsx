import { Info as InformationCircleIcon, PencilSimple as PencilIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { PagerDutyArea, PagerDutyStatus } from '@shared/types.ts'
import pagerdutyMark from '@/assets/pagerduty.svg'
import { Chip, IconBadge, Input } from '@/components/common/ui'
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
import { hostOf } from '@/lib/url'

const PAGERDUTY_GREEN = '#06AC38'
const PAGERDUTY_DOMAIN = 'pagerduty.com'
const DEFAULT_WEB_URL = `https://app.${PAGERDUTY_DOMAIN}`

const CHANGES = ['Notes', 'Acknowledge', 'Resolve', 'Escalate', 'Reassign', 'Snooze']

const AREA_LABELS: Record<PagerDutyArea, string> = {
  incidents: 'Incidents',
  oncall: 'On-call',
}

function webHost(status: PagerDutyStatus): string {
  return status.webUrl.replace('https://', '')
}

function PagerDutyBadge() {
  return (
    <IconBadge color={PAGERDUTY_GREEN}>
      <img src={pagerdutyMark} alt="PagerDuty" className="size-5" />
    </IconBadge>
  )
}

export function usePagerDuty() {
  const { value: status, setValue: setStatus } = useLoad(api.pagerduty, [])
  return { status, setStatus }
}

function PagerDutyConnectModal({
  open,
  status,
  onClose,
  onConnected,
}: ConnectProps<PagerDutyStatus>) {
  const [account, setAccount] = useState('')
  const [apiKey, setApiKey] = useState('')
  const { busy, error, setError, submit } = useConnect(
    () => api.pagerdutyConnect(account, apiKey),
    onConnected,
  )

  useEffect(() => {
    if (!open) return
    setAccount(status?.subdomain ? `${status.subdomain}.${PAGERDUTY_DOMAIN}` : '')
    setApiKey('')
    setError(undefined)
  }, [open])

  const host = hostOf(account)
  const base = host.includes(PAGERDUTY_DOMAIN) ? `https://${host}` : DEFAULT_WEB_URL

  return (
    <ConnectModal
      open={open}
      busy={busy}
      badge={<PagerDutyBadge />}
      title="Connect PagerDuty"
      subtitle="Incidents and on-call for your instances, read-only."
      error={error}
      busyLabel="Checking token"
      ready={Boolean(apiKey.trim())}
      onClose={onClose}
      onSubmit={() => void submit()}
      privacy="The token stays in this computer's credential store and is only sent to PagerDuty. Your PagerDuty admins can see and revoke user tokens. Incidents the agent reads in a thread are sent to GitHub Copilot like any other tool result."
    >
      <div>
        <div className="text-fg text-[13px] font-medium">Account</div>
        <Input
          className="mt-1.5 w-full"
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          placeholder="yourcompany.pagerduty.com, or paste any PagerDuty link"
        />
        <div className="text-muted mt-1.5 px-1 text-[11.5px]">
          Used for links and to pick the US or EU region. Leave empty for the US region.
        </div>
      </div>

      <KeyField
        label="API user token"
        href={`${base}/users`}
        linkLabel="Open PagerDuty"
        value={apiKey}
        onChange={setApiKey}
        placeholder="20 characters"
        hint="My Profile > User Settings > Create API User Token. It reads with your own permissions; OV Agent only reads."
      />
    </ConnectModal>
  )
}

function renderConnect(props: ConnectProps<PagerDutyStatus>) {
  return <PagerDutyConnectModal {...props} />
}

export function PagerDutyCard({
  status,
  setStatus,
}: {
  status?: PagerDutyStatus
  setStatus: (s: PagerDutyStatus) => void
}) {
  return (
    <IntegrationCard
      name="PagerDuty"
      badge={<PagerDutyBadge />}
      status={status}
      setStatus={setStatus}
      connectedDetail={(s) => `${webHost(s)} - ${s.user}`}
      idleDetail="Incidents and on-call for your instances."
      changeLabel="Change token"
      areas={AREA_LABELS}
      keysTitle={(s) => `Token ...${s.keyLast4}`}
      test={api.pagerdutyTest}
      details={
        <div
          className="border-line flex flex-wrap items-center gap-3 border-t px-5 py-3"
          title="Only in threads with Allow changes on, and each change waits for your Approve. Needs a full-access token."
        >
          <span className="text-muted inline-flex items-center gap-1 text-[12px] font-medium">
            Can change <InformationCircleIcon className="text-faint size-3.5" />
          </span>
          <div className="flex flex-wrap gap-1.5">
            {CHANGES.map((label) => (
              <Chip key={label} tone="brand">
                <PencilIcon className="size-3" /> {label}
              </Chip>
            ))}
          </div>
        </div>
      }
      renderConnect={renderConnect}
    />
  )
}

export function PagerDutyAccountRow({
  status,
  setStatus,
}: {
  status?: PagerDutyStatus
  setStatus: (s: PagerDutyStatus) => void
}) {
  return (
    <IntegrationAccountRow
      name="PagerDuty"
      badge={<PagerDutyBadge />}
      status={status}
      setStatus={setStatus}
      connectedDetail={(s) => `Signed in as ${s.user} on ${webHost(s)}`}
      disconnectBody="The token is removed from this computer. Instance matches are kept for next time."
      disconnect={api.pagerdutyDisconnect}
      renderConnect={renderConnect}
    />
  )
}
