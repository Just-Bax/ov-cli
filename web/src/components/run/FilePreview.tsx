import {
  ArrowDownTrayIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DocumentIcon,
  DocumentTextIcon,
  EnvelopeIcon,
  PhotoIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { type ReactNode, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { MessageFile } from '@shared/types.ts'
import { reportError } from '@/components/Toasts'
import { Spinner } from '@/components/ui'
import type { Icon } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

const MAX_TEXT_CHARS = 400_000
const EMAIL_TEXT_SUFFIX = '.txt'

const KIND_ICON: Record<MessageFile['kind'], Icon> = {
  image: PhotoIcon,
  email: EnvelopeIcon,
  text: DocumentTextIcon,
  pdf: DocumentIcon,
  other: DocumentIcon,
}

type Text =
  { state: 'loading' } | { state: 'none' } | { state: 'ready'; text: string; cut: boolean }

function extension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toUpperCase() : 'FILE'
}

function readable(name: string, raw: string): string {
  if (!name.toLowerCase().endsWith('.json')) return raw
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function useText(runId: string, file: MessageFile): Text {
  const [text, setText] = useState<Text>({ state: 'loading' })
  const source =
    file.kind === 'text' ? file.name : file.kind === 'email' ? file.name + EMAIL_TEXT_SUFFIX : ''

  useEffect(() => {
    if (!source) return setText({ state: 'none' })
    const abort = new AbortController()
    setText({ state: 'loading' })
    fetch(api.fileUrl(runId, source), { signal: abort.signal })
      .then(async (res) => {
        if (!res.ok) return setText({ state: 'none' })
        const raw = await res.text()
        setText({
          state: 'ready',
          text: readable(source, raw.slice(0, MAX_TEXT_CHARS)),
          cut: raw.length > MAX_TEXT_CHARS,
        })
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return
        setText({ state: 'none' })
        reportError(e)
      })
    return () => abort.abort()
  }, [runId, source])

  return text
}

function RoundButton({
  label,
  onClick,
  href,
  className,
  children,
}: {
  label: string
  onClick?: () => void
  href?: string
  className?: string
  children: ReactNode
}) {
  const style = cn(
    'flex size-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-white/85 transition-colors hover:bg-white/20 hover:text-white',
    className,
  )
  return href ? (
    <a href={href} download aria-label={label} title={label} className={style}>
      {children}
    </a>
  ) : (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={style}>
      {children}
    </button>
  )
}

function TextBody({ text }: { text: Extract<Text, { state: 'ready' }> }) {
  const lines = text.text.replace(/\r?\n$/, '').split(/\r?\n/)
  const gutter = String(lines.length).length

  return (
    <div className="max-h-full w-full max-w-[1000px] scrollbar-thin overflow-auto rounded-2xl bg-white shadow-[0_20px_60px_rgba(0,0,0,0.35)]">
      <pre className="text-fg py-3 font-mono text-[12.5px] leading-[1.6]">
        {lines.map((line, i) => (
          <div key={i} className="flex hover:bg-[#f4f6f7]">
            <span
              className="text-faint box-content shrink-0 pr-4 pl-4 text-right select-none"
              style={{ width: `${gutter}ch` }}
            >
              {i + 1}
            </span>
            <span className="min-w-0 pr-4 break-all whitespace-pre-wrap">{line || ' '}</span>
          </div>
        ))}
      </pre>
      {text.cut ? (
        <div className="text-muted border-line border-t px-4 py-2 text-[12px]">
          The file is long. Download it to see the rest.
        </div>
      ) : null}
    </div>
  )
}

function NoPreview({ runId, file }: { runId: string; file: MessageFile }) {
  const Icon = KIND_ICON[file.kind]
  return (
    <div className="flex w-[320px] flex-col items-center rounded-2xl bg-white px-6 py-8 text-center shadow-[0_20px_60px_rgba(0,0,0,0.35)]">
      <div className="bg-brand-soft text-brand-strong flex size-14 items-center justify-center rounded-full">
        <Icon className="size-7" />
      </div>
      <div className="text-fg mt-4 w-full truncate text-[14px] font-medium">{file.name}</div>
      <div className="text-muted mt-1 text-[12.5px]">No preview for this file type.</div>
      <a
        href={api.fileUrl(runId, file.name)}
        download
        className="bg-brand text-on-brand hover:bg-brand-strong mt-5 inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-[12.5px] font-medium transition-colors"
      >
        <ArrowDownTrayIcon className="size-4" />
        Download
      </a>
    </div>
  )
}

function Body({ runId, file }: { runId: string; file: MessageFile }) {
  const text = useText(runId, file)
  const url = api.fileUrl(runId, file.name)

  if (file.kind === 'image') {
    return (
      <img
        src={url}
        alt={file.name}
        className="max-h-full max-w-full rounded-lg object-contain shadow-[0_20px_60px_rgba(0,0,0,0.35)]"
      />
    )
  }
  if (file.kind === 'pdf') {
    return (
      <iframe
        src={url}
        title={file.name}
        className="h-full w-full max-w-[1000px] rounded-2xl bg-white shadow-[0_20px_60px_rgba(0,0,0,0.35)]"
      />
    )
  }
  if (text.state === 'loading') return <Spinner className="size-6 text-white/70" />
  if (text.state === 'ready') return <TextBody text={text} />
  return <NoPreview runId={runId} file={file} />
}

function Thumb({
  runId,
  file,
  active,
  onClick,
}: {
  runId: string
  file: MessageFile
  active: boolean
  onClick: () => void
}) {
  const Icon = KIND_ICON[file.kind]
  return (
    <button
      type="button"
      title={file.name}
      aria-label={`Show ${file.name}`}
      onClick={onClick}
      className={cn(
        'flex h-14 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border-2 transition-all',
        active ? 'border-brand opacity-100' : 'border-transparent opacity-55 hover:opacity-90',
      )}
    >
      {file.kind === 'image' ? (
        <img
          src={api.fileUrl(runId, file.name)}
          alt=""
          className="size-full bg-white/10 object-cover"
        />
      ) : (
        <div className="flex size-full flex-col items-center justify-center gap-0.5 bg-white/10 text-white/80">
          <Icon className="size-5" />
          <span className="text-[9.5px] font-semibold tracking-wide">{extension(file.name)}</span>
        </div>
      )}
    </button>
  )
}

export function FilePreview({
  runId,
  files,
  start,
  onClose,
}: {
  runId: string
  files: MessageFile[]
  start: number
  onClose: () => void
}) {
  const [index, setIndex] = useState(start)
  const [shown, setShown] = useState(false)
  const file = files[index]
  const many = files.length > 1
  const step = (by: number) => setIndex((i) => (i + by + files.length) % files.length)

  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(true))
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && many) step(-1)
      if (e.key === 'ArrowRight' && many) step(1)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('keydown', onKey)
    }
  })

  if (!file) throw new Error(`No file at ${index}`)
  const Icon = KIND_ICON[file.kind]

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={file.name}
      className={cn(
        'fixed inset-0 z-[100] flex flex-col bg-[#11181c]/88 backdrop-blur-sm transition-opacity duration-200',
        shown ? 'opacity-100' : 'opacity-0',
      )}
    >
      <div className="flex h-16 shrink-0 items-center gap-3 px-5">
        <Icon className="size-5 shrink-0 text-white/70" />
        <div className="min-w-0 flex-1 truncate text-[14px] font-medium text-white">
          {file.name}
          {many ? (
            <span className="ml-2 font-normal text-white/50">
              {index + 1} / {files.length}
            </span>
          ) : null}
        </div>
        <RoundButton label="Download" href={api.fileUrl(runId, file.name)}>
          <ArrowDownTrayIcon className="size-4.5" />
        </RoundButton>
        <RoundButton label="Close" onClick={onClose}>
          <XMarkIcon className="size-5" />
        </RoundButton>
      </div>

      <div
        className="relative flex min-h-0 flex-1 items-center justify-center px-20 pb-6"
        onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      >
        <div
          key={file.name}
          className="animate-fade-in flex h-full w-full items-center justify-center"
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <Body runId={runId} file={file} />
        </div>
        {many ? (
          <>
            <RoundButton
              label="Previous file"
              onClick={() => step(-1)}
              className="absolute top-1/2 left-5 size-11 -translate-y-1/2"
            >
              <ChevronLeftIcon className="size-5" />
            </RoundButton>
            <RoundButton
              label="Next file"
              onClick={() => step(1)}
              className="absolute top-1/2 right-5 size-11 -translate-y-1/2"
            >
              <ChevronRightIcon className="size-5" />
            </RoundButton>
          </>
        ) : null}
      </div>

      {many ? (
        <div className="flex shrink-0 scrollbar-thin justify-center gap-2 overflow-x-auto px-5 pb-5">
          {files.map((f, i) => (
            <Thumb
              key={f.name}
              runId={runId}
              file={f}
              active={i === index}
              onClick={() => setIndex(i)}
            />
          ))}
        </div>
      ) : null}
    </div>,
    document.body,
  )
}
