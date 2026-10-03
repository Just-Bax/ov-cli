import { ArrowUp, Paperclip, Square, X } from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/lib/cn'

let pasteCounter = 0

export function Composer({
  placeholder,
  onSend,
  onStop,
  busy,
  disabled,
  allowFiles,
  extras,
  autoFocus,
  size = 'md',
  queueWhileBusy,
}: {
  placeholder: string
  onSend: (text: string, files: File[]) => void | Promise<void>
  onStop?: () => void
  busy?: boolean
  disabled?: boolean
  allowFiles?: boolean
  extras?: ReactNode
  autoFocus?: boolean
  size?: 'md' | 'lg'
  /** Allow sending while busy; the message is queued as a follow-up. */
  queueWhileBusy?: boolean
}) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const canSend =
    (!busy || Boolean(queueWhileBusy)) && !disabled && (text.trim().length > 0 || files.length > 0)

  const send = async () => {
    if (!canSend) return
    const value = text.trim()
    const attached = files
    setText('')
    setFiles([])
    await onSend(value, attached)
  }

  const textRef = useRef<HTMLTextAreaElement>(null)
  const addFiles = (list: FileList | File[] | null) => {
    if (allowFiles && list?.length) setFiles((f) => [...f, ...Array.from(list)])
  }

  /** Files from a paste: screenshots, copied images, or files copied in Explorer. Returns true if any. */
  const takeClipboardFiles = (data: DataTransfer | null): boolean => {
    if (!allowFiles || !data) return false
    const found: File[] = []
    for (const item of Array.from(data.items)) {
      if (item.kind !== 'file') continue
      const file = item.getAsFile()
      if (!file) continue
      // Screenshots arrive as "image.png"; give each a unique, readable name.
      const generic = /^image\.\w+$/i.test(file.name) || !file.name
      const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
      const stamp = new Date().toISOString().slice(11, 19).replace(/:/g, '')
      found.push(
        generic
          ? new File([file], `pasted-${stamp}-${++pasteCounter}.${ext}`, { type: file.type })
          : file,
      )
    }
    if (!found.length) return false
    addFiles(found)
    return true
  }

  // Ctrl+V anywhere on the page attaches files here, unless another field has focus.
  useEffect(() => {
    if (!allowFiles) return
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target === textRef.current) return
      if (
        target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      )
        return
      if (takeClipboardFiles(e.clipboardData)) {
        e.preventDefault()
        textRef.current?.focus()
      }
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
    // takeClipboardFiles only depends on allowFiles and the stable setFiles.
  }, [allowFiles])

  const previews = useMemo(
    () => files.map((f) => (f.type.startsWith('image/') ? URL.createObjectURL(f) : undefined)),
    [files],
  )
  useEffect(() => () => previews.forEach((u) => u && URL.revokeObjectURL(u)), [previews])

  return (
    <div
      onDragOver={(e) => allowFiles && e.preventDefault()}
      onDrop={(e) => {
        if (!allowFiles) return
        e.preventDefault()
        addFiles(e.dataTransfer.files)
      }}
      className="border-line-strong focus-within:border-brand rounded-[22px] border bg-white shadow-[0_2px_12px_rgba(38,50,56,0.06)] transition-colors"
    >
      {files.length ? (
        <div className="flex flex-wrap items-end gap-2 px-3 pt-3">
          {files.map((f, i) =>
            previews[i] ? (
              <div key={i} className="group/thumb relative">
                <img
                  src={previews[i]}
                  alt={f.name}
                  title={f.name}
                  className="border-line bg-raised size-16 rounded-xl border object-cover"
                />
                <button
                  type="button"
                  title="Remove"
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="bg-fg absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full text-white opacity-0 shadow transition-opacity group-hover/thumb:opacity-100"
                >
                  <X className="size-3" />
                </button>
              </div>
            ) : (
              <span
                key={i}
                className="bg-canvas text-text inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px]"
              >
                <Paperclip className="size-3" />
                <span className="max-w-[180px] truncate">{f.name}</span>
                <button
                  type="button"
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="text-faint hover:text-fg"
                >
                  <X className="size-3" />
                </button>
              </span>
            ),
          )}
        </div>
      ) : null}
      <textarea
        ref={textRef}
        autoFocus={autoFocus}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onPaste={(e) => {
          // Keep pasted text as text; only take over when the clipboard holds files.
          if (takeClipboardFiles(e.clipboardData) && !e.clipboardData.getData('text/plain'))
            e.preventDefault()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            void send()
          }
        }}
        rows={1}
        placeholder={placeholder}
        className={cn(
          'placeholder:text-faint block field-sizing-content max-h-60 w-full resize-none scrollbar-thin bg-transparent px-4 text-[14px] outline-none',
          size === 'lg' ? 'min-h-[56px] pt-4' : 'min-h-[44px] pt-3',
        )}
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        {allowFiles ? (
          <>
            <button
              type="button"
              title="Attach files"
              onClick={() => fileRef.current?.click()}
              className="text-muted hover:bg-raised hover:text-fg flex size-8 items-center justify-center rounded-full"
            >
              <Paperclip className="size-4" />
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              onChange={(e) => addFiles(e.target.files)}
            />
          </>
        ) : null}
        {extras}
        <div className="flex-1" />
        {busy && onStop && !text.trim() && !files.length ? (
          <button
            type="button"
            title="Stop"
            onClick={onStop}
            className="bg-fg flex size-8 items-center justify-center rounded-full text-white hover:opacity-85"
          >
            <Square className="size-3 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            title={busy ? 'Queue as follow-up' : 'Send'}
            disabled={!canSend}
            onClick={() => void send()}
            className="bg-brand hover:bg-brand-strong disabled:bg-line-strong flex size-8 items-center justify-center rounded-full text-white transition-colors"
          >
            <ArrowUp className="size-4" />
          </button>
        )}
      </div>
    </div>
  )
}
