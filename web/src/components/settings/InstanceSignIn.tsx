import { Key as KeyIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Instance } from '@shared/types.ts'
import { dialog } from '@/components/common/Dialog'
import { Button, Chip } from '@/components/common/ui'
import { api } from '@/lib/api'
import { REMEMBER_DAYS, rememberedUntil, signInState } from '@/lib/signin'

function Separator() {
  return <span aria-hidden className="bg-line-strong size-[3px] shrink-0 rounded-full" />
}

export function SignInLine({
  instance,
  onRemembered,
  onFailed,
}: {
  instance: Instance
  onRemembered: (list: Instance[]) => void
  onFailed: () => void
}) {
  const [busy, setBusy] = useState(false)
  const state = signInState(instance)
  const canKeep = instance.mode === 'session' && state.stage === 'ok'

  const keep = async () => {
    setBusy(true)
    try {
      onRemembered(await api.rememberInstance(instance.alias))
    } catch (e) {
      onFailed()
      await dialog.alert(`Could not keep ${instance.host} signed in`, (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="text-muted flex min-w-0 flex-1 items-center gap-1.5 text-[11.5px]">
      <Separator />
      <span className="truncate" title={state.summary}>
        {state.summary}
      </span>
      {canKeep ? (
        <>
          <Separator />
          <button
            type="button"
            disabled={busy}
            title={`Creates an API token in your name from this web session, if it still works. You won't be asked again until ${rememberedUntil()}.`}
            onClick={() => void keep()}
            className="text-brand-strong shrink-0 font-medium hover:underline disabled:opacity-60"
          >
            {busy ? 'Creating token' : `Keep signed in ${REMEMBER_DAYS} days`}
          </button>
        </>
      ) : null}
    </span>
  )
}

export function SignInStatus({ instance }: { instance: Instance }) {
  const { chip } = signInState(instance)
  return chip ? <Chip tone={chip.tone}>{chip.text}</Chip> : null
}

export function SignInButton({
  instance,
  busy,
  onSignIn,
}: {
  instance: Instance
  busy: boolean
  onSignIn: () => void
}) {
  const { stage } = signInState(instance)
  const needed = stage === 'ended' || stage === 'expired'

  const label =
    instance.mode === 'token'
      ? 'Replace token'
      : stage === 'soon'
        ? 'Renew'
        : stage === 'ok'
          ? 'Sign in again'
          : 'Sign in'

  return (
    <Button
      size="sm"
      variant={needed ? 'secondary' : 'ghost'}
      busy={busy}
      title={
        instance.mode === 'remembered' && !needed
          ? 'Creates a new token. The current one stays active in Admin > Auth Tokens until it expires.'
          : undefined
      }
      onClick={onSignIn}
    >
      <KeyIcon className="size-3.5" />
      {busy ? 'Signing in' : label}
    </Button>
  )
}
