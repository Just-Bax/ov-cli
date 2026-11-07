import {
  ArrowUp as ArrowUpIcon,
  Paperclip as PaperClipIcon,
  Stop as StopIcon,
} from '@phosphor-icons/react'
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { notify, reportError } from '@/components/common/Toasts'
import { localFile, type PreviewFile } from '@/components/run/FilePreview'
import { cn } from '@/lib/cn'
import { useObjectUrls, useWindowEvent } from '@/lib/hooks'
import { isEditableTarget } from '@/lib/dom'
import { forgetDraft, loadFiles, loadText, saveFiles, saveText } from '@/lib/drafts'
import { type Attached, Attachments, attachmentKey } from './Attachments'

const DRAFT_SAVE_MS = 300
const UNNAMED_PASTE = 'image.png'

export function Composer({
  placeholder,
  onSend,
  onStop,
  busy,
  allowFiles,
  sentFiles = [],
  onRemoveSentFile,
  extras,
  autoFocus,
  size = 'md',
  queueWhileBusy,
  draft,
  draftKey,
  submitLabel,
  allowEmpty,
  busyAction,
  idleAction,
  onKeyDown,
}: {
  placeholder: string
  onSend: (text: string, files: File[], alternate: boolean) => void | Promise<void>
  busyAction?: (alternate: boolean) => { label: string; icon: ReactNode }
  idleAction?: ReactNode
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => boolean
  onStop?: () => void
  busy?: boolean
  allowFiles?: boolean
  sentFiles?: PreviewFile[]
  onRemoveSentFile?: (name: string) => void
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
  const [alternate, setAlternate] = useState(false)
  const filesLoaded = useRef(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const urls = useObjectUrls(files)
  const attachedCount = files.length + sentFiles.length
  const canSend =
    (!busy || Boolean(queueWhileBusy)) &&
    (Boolean(allowEmpty) || text.trim().length > 0 || attachedCount > 0)
  const hasContent = text.trim().length > 0 || attachedCount > 0
  const showStop = busy && onStop && (submitLabel || !hasContent)
  const action = busy && hasContent ? busyAction?.(alternate) : undefined

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
  useWindowEvent('keydown', (e) => setAlternate(e.ctrlKey || e.metaKey))
  useWindowEvent('keyup', (e) => setAlternate(e.ctrlKey || e.metaKey))
  useWindowEvent('blur', () => setAlternate(false))

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
    if (!allowFiles || !list?.length) return

    const taken = new Set([...files, ...sentFiles].map((f) => attachmentKey(f.name, f.size)))
    const fresh: File[] = []
    const repeated: string[] = []
    for (const file of Array.from(list)) {
      const key = attachmentKey(file.name, file.size)
      if (taken.has(key)) repeated.push(file.name)
      else fresh.push(file)
      taken.add(key)
    }

    if (repeated.length) notify(`Already attached: ${repeated.join(', ')}`)
    if (fresh.length) setFiles((current) => [...current, ...fresh])
  }

  const takeClipboardFiles = (data: DataTransfer | null): boolean => {
    if (!allowFiles || !data) return false

    const found = Array.from(data.items)
      .map((item) => (item.kind === 'file' ? item.getAsFile() : null))
      .filter((file): file is File => file !== null)
      .map((file) => (file.name ? file : new File([file], UNNAMED_PASTE, { type: file.type })))
    if (!found.length) return false

    addFiles(found)
    return true
  }

  useWindowEvent('paste', (e) => {
    if (isEditableTarget(e.target) || !takeClipboardFiles(e.clipboardData)) return
    e.preventDefault()
    textRef.current?.focus()
  })

  const attachments: Attached[] = [
    ...sentFiles.map((file) => ({
      key: `sent:${file.name}`,
      file,
      onRemove: () => onRemoveSentFile?.(file.name),
    })),
    ...files.flatMap((file) => {
      const url = urls.get(file)
      if (!url) return []

      return [
        {
          key: url,
          file: localFile(file, url),
          onRemove: () => setFiles((current) => current.filter((f) => f !== file)),
        },
      ]
    }),
  ]

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
      <Attachments items={attachments} />
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
          if (onKeyDown?.(e)) {
            e.preventDefault()
            return
          }
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
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []))
                e.target.value = ''
              }}
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
        ) : showStop ? null : action ? (
          <button
            type="button"
            title={action.label}
            aria-label={action.label}
            disabled={!canSend}
            onClick={() => void send(alternate)}
            className="bg-brand hover:bg-brand-strong disabled:bg-line-strong flex size-8 items-center justify-center rounded-full text-white transition-colors"
          >
            {action.icon}
          </button>
        ) : !busy && !hasContent && idleAction ? (
          idleAction
        ) : (
          <button
            type="button"
            title="Send"
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
