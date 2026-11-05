import {
  CaretDown as ChevronDownIcon,
  Eye as EyeIcon,
  type Icon,
  Lightning as LightningIcon,
  LockOpen as LockOpenIcon,
  ShieldCheck as ShieldCheckIcon,
} from '@phosphor-icons/react'
import type { Access } from '@shared/types.ts'
import { useEffect, useRef, useState } from 'react'
import { dialog } from '@/components/common/Dialog'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useClickOutside, useLoad } from '@/lib/hooks'

interface Mode {
  value: Access
  label: string
  about: string
  icon: Icon
  tone: string
  bar: string
}

const METER_STEPS = 4

const ACCESS_MODES: Mode[] = [
  {
    value: 'read',
    label: 'Read-only',
    about: 'Reads and proposes. Changes nothing.',
    icon: EyeIcon,
    tone: 'text-ok',
    bar: 'bg-ok',
  },
  {
    value: 'ask',
    label: 'Always ask',
    about: 'Asks before every change.',
    icon: ShieldCheckIcon,
    tone: 'text-brand-strong',
    bar: 'bg-brand',
  },
  {
    value: 'auto',
    label: 'Auto',
    about: 'Asks only before risky changes.',
    icon: LightningIcon,
    tone: 'text-warn',
    bar: 'bg-warn',
  },
  {
    value: 'full',
    label: 'Full access',
    about: 'Never asks. Every change runs.',
    icon: LockOpenIcon,
    tone: 'text-danger',
    bar: 'bg-danger',
  },
]

export function accessMode(value: Access): Mode {
  const found = ACCESS_MODES.find((m) => m.value === value)
  if (!found) throw new Error(`Unknown access mode ${value}`)
  return found
}

function AccessMeter({ value }: { value: Access }) {
  const mode = accessMode(value)
  const level = ACCESS_MODES.indexOf(mode) + 1

  return (
    <span className="inline-flex shrink-0 items-center gap-[3px]" aria-hidden>
      {Array.from({ length: METER_STEPS }, (_, i) => (
        <i
          key={i}
          className={cn('h-3 w-[5px] rounded-[2px]', i < level ? mode.bar : 'bg-line-strong')}
        />
      ))}
    </span>
  )
}

const CONFIRM: Partial<Record<Access, () => Promise<boolean>>> = {
  auto: () =>
    dialog.confirm({
      title: 'Let the agent make changes on its own?',
      body: (
        <>
          Edits, saves, imports, wizard steps and commits run without asking. Deletes, bulk changes,
          force pushes, merges, deploys and permission changes still wait for your{' '}
          <b className="text-fg">Approve</b>.
        </>
      ),
      confirmLabel: 'Use Auto',
      tone: 'warn',
    }),
  full: () =>
    dialog.confirm({
      title: 'Give the agent full access?',
      body: (
        <>
          Every change runs without a check or a question, including deletes, force pushes, merges
          and deploys. Use it only on instances and repositories you can restore.
        </>
      ),
      confirmLabel: 'Use Full access',
      tone: 'danger',
    }),
}

export function AccessPicker({
  value,
  onChange,
}: {
  value: Access
  onChange: (v: Access) => void | Promise<unknown>
}) {
  const [local, setLocal] = useState(value)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const { value: status } = useLoad(api.status, [])

  useEffect(() => setLocal(value), [value])
  useClickOutside([menuRef, triggerRef], () => setOpen(false), open)

  const current = accessMode(local)
  const offered = ACCESS_MODES.filter((m) => m.value !== 'full' || status?.fullAccess)

  const pick = async (next: Access) => {
    setOpen(false)

    if (next === local) return

    const confirm = CONFIRM[next]
    if (confirm && !(await confirm())) return

    const previous = local
    setLocal(next)
    setSaving(true)

    try {
      await onChange(next)
    } catch (e) {
      setLocal(previous)
      await dialog.alert('Could not change access', (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        disabled={saving}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        title={current.about}
        className={cn(
          'inline-flex h-8 items-center gap-2 rounded-full border bg-white px-3 text-[12px] font-medium whitespace-nowrap transition-colors outline-none',
          local === 'full'
            ? 'border-danger/45 text-danger hover:bg-danger-soft/40'
            : 'border-line-strong text-text hover:bg-raised',
          saving && 'busy-sweep',
        )}
      >
        <AccessMeter value={local} />
        {current.label}
        <ChevronDownIcon
          className={cn('size-3 opacity-60 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open ? (
        <div
          ref={menuRef}
          role="menu"
          className="border-line-strong/70 animate-pop absolute bottom-full left-0 z-[200] mb-2 w-[340px] rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
        >
          {offered.map((m) => {
            const on = m.value === local

            return (
              <button
                key={m.value}
                type="button"
                role="menuitemradio"
                aria-checked={on}
                onClick={() => void pick(m.value)}
                className={cn(
                  'hover:bg-raised grid w-full grid-cols-[18px_1fr_auto] items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors',
                  on &&
                    (m.value === 'full'
                      ? 'shadow-[inset_0_0_0_1.5px_var(--color-danger)]'
                      : 'shadow-[inset_0_0_0_1.5px_var(--color-brand)]'),
                )}
              >
                <m.icon
                  weight="bold"
                  className={cn('size-4', m.value === 'full' ? 'text-danger' : 'text-text')}
                />
                <span className="min-w-0">
                  <span
                    className={cn(
                      'block text-[12.5px] font-medium',
                      m.value === 'full' ? 'text-danger' : 'text-fg',
                    )}
                  >
                    {m.label}
                  </span>
                  <span className="text-muted block truncate text-[11.5px]">{m.about}</span>
                </span>
                <AccessMeter value={m.value} />
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
