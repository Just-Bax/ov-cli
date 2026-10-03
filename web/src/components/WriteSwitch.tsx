import { useEffect, useState } from 'react'
import { dialog } from '@/components/Dialog'
import { Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'

/** `onChange` may be async; if it throws, the switch flips back and the error is shown. */
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
        title: 'Allow changes in this run?',
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
        'flex h-8 items-center gap-2 rounded-full px-2.5 text-[12px] transition-colors',
        local ? 'bg-warn-soft text-warn font-medium' : 'text-muted hover:bg-raised hover:text-fg',
      )}
    >
      {saving ? (
        <Spinner className="size-3.5" />
      ) : (
        <span
          className={cn(
            'relative h-4 w-7 rounded-full transition-colors',
            local ? 'bg-warn' : 'bg-line-strong',
          )}
        >
          <span
            className={cn(
              'absolute top-0.5 size-3 rounded-full bg-white shadow transition-all',
              local ? 'left-3.5' : 'left-0.5',
            )}
          />
        </span>
      )}
      {local ? 'Changes allowed' : 'Read-only'}
    </button>
  )
}
