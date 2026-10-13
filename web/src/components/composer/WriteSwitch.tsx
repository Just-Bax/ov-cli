import { useEffect, useState } from 'react'
import { dialog } from '@/components/common/Dialog'
import { Spinner, SWITCH_TRACK, SwitchKnob } from '@/components/common/ui'
import { cn } from '@/lib/cn'

export function WriteSwitch({
  value,
  onChange,
}: {
  value: boolean
  onChange: (v: boolean) => void | Promise<unknown>
}) {
  const [local, setLocal] = useState(value)
  const [saving, setSaving] = useState(false)

  useEffect(() => setLocal(value), [value])

  const toggle = async () => {
    const next = !local
    if (next) {
      const ok = await dialog.confirm({
        title: 'Allow changes in this thread?',
        body: (
          <>
            The agent will be able to change data and configuration on the instance through ov.
            Every change still shows you the exact command and waits for your{' '}
            <b className="text-fg">Approve</b> before it runs. You can turn this off at any time.
          </>
        ),
        confirmLabel: 'Allow changes',
        tone: 'warn',
      })
      if (!ok) return
    }

    setLocal(next)
    setSaving(true)
    try {
      await onChange(next)
    } catch (e) {
      setLocal(!next)
      await dialog.alert('Could not change write access', (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={local}
      disabled={saving}
      onClick={() => void toggle()}
      title={
        local
          ? 'The agent may apply changes; each one needs your approval'
          : 'Read-only: the agent can only look and propose'
      }
      className={cn(
        'flex h-8 shrink-0 items-center gap-2 rounded-full px-3 text-[12px] font-medium whitespace-nowrap transition-colors',
        local ? 'bg-warn-soft text-warn' : 'bg-raised text-text hover:bg-line',
      )}
    >
      {saving ? (
        <Spinner className="size-3.5" />
      ) : (
        <span className={cn(SWITCH_TRACK, local ? 'bg-warn' : 'bg-line-strong')}>
          <SwitchKnob on={local} />
        </span>
      )}
      {local ? 'Changes allowed' : 'Read-only'}
    </button>
  )
}
