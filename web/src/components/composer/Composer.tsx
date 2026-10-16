import {
  ArrowUp as ArrowUpIcon,
  Paperclip as PaperClipIcon,
  Stop as StopIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { reportError } from '@/components/common/Toasts'
import { cn } from '@/lib/cn'
import { useWindowEvent } from '@/lib/hooks'
import { isEditableTarget } from '@/lib/dom'
import { forgetDraft, loadFiles, loadText, saveFiles, saveText } from '@/lib/drafts'

const DRAFT_SAVE_MS = 300
const ISO_TIME_CHARS = [11, 19] as const

let pasteCounter = 0

export function Composer({
  placeholder,
  onSend,
  onStop,
  busy,
  allowFiles,
  extras,
  autoFocus,
  size = 'md',
  queueWhileBusy,
  draft,
  draftKey,
  busyHint,
  submitLabel,
  allowEmpty,
}: {
  placeholder: string
  onSend: (text: string, files: File[], alternate: boolean) => void | Promise<void>
  busyHint?: (alternate: boolean) => string
  onStop?: () => void
  busy?: boolean
  allowFiles?: boolean
  extras?: ReactNode
  autoFocus?: boolean
  size?: 'md' | 'lg'
  queueWhileBusy?: boolean
  draft?: { text: string; at: number }
  draftKey: string
  submitLabel?: (text: string) => string
  allowEmpty?: boolean
}) {
  const [text, setText] = useState(() => loadText(draftKey))
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<(string | undefined)[]>([])
  const filesLoaded = useRef(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const canSend =
    (!busy || Boolean(queueWhileBusy)) &&
    (Boolean(allowEmpty) || text.trim().length > 0 || files.length > 0)
  const showStop = busy && onStop && (submitLabel || (!text.trim() && !files.length))

  useEffect(() => {
    let alive = true
    filesLoaded.current = false
    setText(loadText(draftKey))
    loadFiles(draftKey)
      .then((found) => {
        if (!alive) return
        setFiles(found)
        filesLoaded.current = true
      })
      .catch(reportError)

    return () => {
      alive = false
    }
  }, [draftKey])

  useEffect(() => {
    const timer = setTimeout(() => saveText(draftKey, text), DRAFT_SAVE_MS)
    return () => clearTimeout(timer)
  }, [draftKey, text])

  useEffect(() => {
    if (filesLoaded.current) void saveFiles(draftKey, files).catch(reportError)
  }, [draftKey, files])

  useWindowEvent('beforeunload', () => saveText(draftKey, textRef.current?.value ?? ''))

  const send = async (alternate = false) => {
    if (!canSend) return

    const value = text.trim()
    const attached = files
    setText('')
    setFiles([])
    try {
      await onSend(value, attached, alternate)
      forgetDraft(draftKey)
    } catch {
      setText(value)
      setFiles(attached)
    }
  }

  useEffect(() => {
    if (!draft) return

    setText(draft.text)
    requestAnimationFrame(() => {
      const el = textRef.current
      if (!el) return
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
      el.scrollTop = el.scrollHeight
    })
  }, [draft?.at])

  const addFiles = (list: FileList | File[] | null) => {
    if (allowFiles && list?.length) setFiles((f) => [...f, ...Array.from(list)])
  }

  const takeClipboardFiles = (data: DataTransfer | null): boolean => {
    if (!allowFiles || !data) return false

    const found: File[] = []
    for (const item of Array.from(data.items)) {
      const file = item.kind === 'file' ? item.getAsFile() : null
      if (!file) continue

      const unnamedScreenshot = /^image\.\w+$/i.test(file.name) || !file.name
      const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
      const stamp = new Date()
        .toISOString()
        .slice(...ISO_TIME_CHARS)
        .replace(/:/g, '')
      found.push(
        unnamedScreenshot
          ? new File([file], `pasted-${stamp}-${++pasteCounter}.${ext}`, { type: file.type })
          : file,
      )
    }

    if (!found.length) return false

    addFiles(found)
    return true
  }

  useEffect(() => {
    if (!allowFiles) return

    const onPagePaste = (e: ClipboardEvent) => {
      if (isEditableTarget(e.target) || !takeClipboardFiles(e.clipboardData)) return
      e.preventDefault()
      textRef.current?.focus()
    }
    document.addEventListener('paste', onPagePaste)
    return () => document.removeEventListener('paste', onPagePaste)
  }, [allowFiles])

  useEffect(() => {
    const urls = files.map((f) =>
      f.type.startsWith('image/') ? URL.createObjectURL(f) : undefined,
    )
    setPreviews(urls)
    return () => urls.forEach((u) => u && URL.revokeObjectURL(u))
  }, [files])

  return (
    <div
      onDragOver={(e) => allowFiles && e.preventDefault()}
      onDrop={(e) => {
        if (!allowFiles) return
        e.preventDefault()
        addFiles(e.dataTransfer.files)
      }}
      className="border-line-strong focus-within:border-brand rounded-[26px] border bg-white shadow-[0_2px_12px_rgba(38,50,56,0.06)] transition-colors"
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
                  className="border-line bg-raised size-16 rounded-2xl border object-cover"
                />
                <button
                  type="button"
                  title="Remove"
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="bg-fg absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full text-white opacity-0 shadow transition-opacity group-hover/thumb:opacity-100"
                >
                  <XMarkIcon className="size-3" />
                </button>
              </div>
            ) : (
              <span
                key={i}
                className="bg-canvas text-text inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12px]"
              >
                <PaperClipIcon className="size-3" />
                <span className="max-w-[180px] truncate">{f.name}</span>
                <button
                  type="button"
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="text-faint hover:text-fg"
                >
                  <XMarkIcon className="size-3" />
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
          const tookFiles = takeClipboardFiles(e.clipboardData)
          const hasText = Boolean(e.clipboardData.getData('text/plain'))
          if (tookFiles && !hasText) e.preventDefault()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            void send(e.ctrlKey || e.metaKey)
          }
        }}
        rows={1}
        placeholder={placeholder}
        className={cn(
          'placeholder:text-faint block field-sizing-content max-h-60 w-full resize-none scrollbar-thin bg-transparent px-4 text-[14px] outline-none',
          size === 'lg' ? 'min-h-[72px] pt-3.5 pb-2' : 'min-h-[60px] pt-3 pb-1.5',
        )}
      />
      <div className="flex items-center gap-1.5 px-2.5 pb-2.5">
        {allowFiles ? (
          <>
            <button
              type="button"
              title="Attach files"
              onClick={() => fileRef.current?.click()}
              className="text-muted bg-raised hover:bg-line hover:text-fg flex size-8 items-center justify-center rounded-full"
            >
              <PaperClipIcon className="size-4" />
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
        {showStop ? (
          <button
            type="button"
            title="Stop"
            onClick={onStop}
            className="bg-fg flex size-8 items-center justify-center rounded-full text-white hover:opacity-85"
          >
            <StopIcon weight="fill" className="size-3" />
          </button>
        ) : null}
        {submitLabel ? (
          <button
            type="button"
            disabled={!canSend}
            onClick={() => void send()}
            className="bg-brand hover:bg-brand-strong disabled:bg-line-strong text-on-brand h-8 rounded-full px-4 text-[12.5px] font-medium transition-colors"
          >
            {submitLabel(text.trim())}
          </button>
        ) : showStop ? null : (
          <button
            type="button"
            title={busy && busyHint ? busyHint(false) : 'Send'}
            disabled={!canSend}
            onClick={() => void send()}
            className="bg-brand hover:bg-brand-strong disabled:bg-line-strong flex size-8 items-center justify-center rounded-full text-white transition-colors"
          >
            <ArrowUpIcon className="size-4" />
          </button>
        )}
      </div>
    </div>
  )
}
