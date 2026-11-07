import { X as XMarkIcon } from '@phosphor-icons/react'
import { useState } from 'react'
import { FilePreview, KIND_ICON, type PreviewFile } from '@/components/run/FilePreview'
import { fileSize } from '@/lib/text'

export interface Attached {
  key: string
  file: PreviewFile
  onRemove: () => void
}

export function attachmentKey(name: string, size?: number): string {
  return `${size ?? ''}:${name}`
}

function Chip({
  file,
  onOpen,
  onRemove,
}: {
  file: PreviewFile
  onOpen: () => void
  onRemove: () => void
}) {
  const Icon = KIND_ICON[file.kind]

  return (
    <span className="border-line inline-flex h-8 max-w-[280px] items-center gap-1.5 rounded-full border bg-white pr-1 pl-1.5 text-[12.5px]">
      <button
        type="button"
        title={`Preview ${file.name}`}
        aria-label={`Preview ${file.name}`}
        onClick={onOpen}
        className="group/chip flex min-w-0 items-center gap-1.5"
      >
        {file.kind === 'image' ? (
          <img
            src={file.url}
            alt=""
            className="border-line size-5 shrink-0 rounded-md border object-cover"
          />
        ) : (
          <Icon className="text-muted size-4 shrink-0" />
        )}
        <span className="text-brand-strong truncate group-hover/chip:underline">{file.name}</span>
      </button>
      {file.size !== undefined ? (
        <span className="text-faint shrink-0 text-[11.5px]">{fileSize(file.size)}</span>
      ) : null}
      <button
        type="button"
        title="Remove"
        aria-label={`Remove ${file.name}`}
        onClick={onRemove}
        className="text-faint hover:text-fg hover:bg-raised flex size-6 shrink-0 items-center justify-center rounded-full transition-colors"
      >
        <XMarkIcon className="size-3" />
      </button>
    </span>
  )
}

export function Attachments({ items }: { items: Attached[] }) {
  const [open, setOpen] = useState<number>()
  if (!items.length) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5 px-3 pt-3">
      {items.map(({ key, file, onRemove }, index) => (
        <Chip key={key} file={file} onOpen={() => setOpen(index)} onRemove={onRemove} />
      ))}
      {open !== undefined && items[open] ? (
        <FilePreview
          files={items.map((item) => item.file)}
          start={open}
          onClose={() => setOpen(undefined)}
        />
      ) : null}
    </div>
  )
}
