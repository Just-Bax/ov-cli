import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function MenuItem({
  icon,
  label,
  title,
  hint,
  onClick,
  onHover,
  active,
  danger,
  disabled,
  trailing,
}: {
  icon: ReactNode
  label: string
  title?: string
  hint?: string
  onClick?: () => void
  onHover?: () => void
  active?: boolean
  danger?: boolean
  disabled?: boolean
  trailing?: ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      title={title}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={onHover}
      className={cn(
        'flex h-8 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        active
          ? 'bg-brand-soft text-brand-strong'
          : danger
            ? 'text-danger hover:bg-danger-soft'
            : 'text-fg enabled:hover:bg-raised',
      )}
    >
      <span className={active ? 'text-brand-strong' : danger ? 'text-danger' : 'text-muted'}>
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint ? <span className="text-faint shrink-0 text-[11px]">{hint}</span> : null}
      {trailing}
    </button>
  )
}
