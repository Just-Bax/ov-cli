import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'

/** Double-click to rename; Enter or leaving the field saves, Escape cancels. */
export function EditableTitle({
  value,
  onSave,
  className,
  inputClassName,
}: {
  value: string
  onSave: (title: string) => Promise<unknown> | void
  className?: string
  inputClassName?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.select()
  }, [editing])

  const commit = async () => {
    setEditing(false)
    const next = draft.trim()
    if (next && next !== value) await onSave(next)
  }

  if (!editing)
    return (
      <span
        className={cn('cursor-text', className)}
        onDoubleClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setDraft(value)
          setEditing(true)
        }}
      >
        {value}
      </span>
    )

  return (
    <input
      ref={inputRef}
      value={draft}
      maxLength={120}
      onChange={(e) => setDraft(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Enter') void commit()
        if (e.key === 'Escape') setEditing(false)
      }}
      onBlur={() => void commit()}
      className={cn(
        'border-brand text-fg w-full min-w-0 rounded-full border bg-white px-3 outline-none',
        inputClassName,
      )}
    />
  )
}
