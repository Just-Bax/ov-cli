import {
  DownloadSimple as ArrowDownTrayIcon,
  CaretLeft as ChevronLeftIcon,
  CaretRight as ChevronRightIcon,
  File as DocumentIcon,
  FileText as DocumentTextIcon,
  EnvelopeSimple as EnvelopeIcon,
  Image as PhotoIcon,
  X as XMarkIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { MessageFile } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { type Icon, Shimmer } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useEnterTransition, useWindowEvent } from '@/lib/hooks'
import { useLayer } from '@/lib/layers'
import { kindOf } from '@/lib/optimistic'

const MAX_TEXT_CHARS = 400_000
const EMAIL_TEXT_SUFFIX = '.txt'

export const KIND_ICON: Record<MessageFile['kind'], Icon> = {
  image: PhotoIcon,
  email: EnvelopeIcon,
  text: DocumentTextIcon,
  pdf: DocumentIcon,
  other: DocumentIcon,
}

type Text =
  { state: 'loading' } | { state: 'none' } | { state: 'ready'; text: string; cut: boolean }

export interface PreviewFile {
  name: string
  kind: MessageFile['kind']
  url: string
  textUrl?: string
  size?: number
}

export function sentFile(runId: string, file: MessageFile): PreviewFile {
  const url = api.fileUrl(runId, file.name)
  const textUrl =
    file.kind === 'text'
      ? url
      : file.kind === 'email'
        ? api.fileUrl(runId, file.name + EMAIL_TEXT_SUFFIX)
        : undefined

  return {
    name: file.name,
    kind: file.kind,
    url: file.kind === 'image' ? api.imageUrl(runId, file) : url,
    textUrl,
    size: file.size,
  }
}

export function localFile(file: File, url: string): PreviewFile {
  const kind = kindOf(file)
  return { name: file.name, kind, url, textUrl: kind === 'text' ? url : undefined, size: file.size }
}

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

function useText({ name, textUrl }: PreviewFile): Text {
  const [text, setText] = useState<Text>({ state: 'loading' })

  useEffect(() => {
    if (!textUrl) return setText({ state: 'none' })

    const abort = new AbortController()
    setText({ state: 'loading' })
    fetch(textUrl, { signal: abort.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Cannot preview ${name}: ${res.status} ${res.statusText}`)

        const raw = await res.text()
        setText({
          state: 'ready',
          text: readable(name, raw.slice(0, MAX_TEXT_CHARS)),
          cut: raw.length > MAX_TEXT_CHARS,
        })
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return
        setText({ state: 'none' })
        reportError(e)
      })

    return () => abort.abort()
  }, [name, textUrl])

  return text
}

function RoundButton({
  label,
  onClick,
  href,
  download,
  className,
  children,
}: {
  label: string
  onClick?: () => void
  href?: string
  download?: string
  className?: string
  children: ReactNode
}) {
  const style = cn(
    'flex size-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-white/85 transition-colors hover:bg-white/20 hover:text-white',
    className,
  )

  return href ? (
    <a href={href} download={download} aria-label={label} title={label} className={style}>
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

function NoPreview({ file }: { file: PreviewFile }) {
  const Icon = KIND_ICON[file.kind]

  return (
    <div className="flex w-[320px] flex-col items-center rounded-2xl bg-white px-6 py-8 text-center shadow-[0_20px_60px_rgba(0,0,0,0.35)]">
      <div className="bg-brand-soft text-brand-strong flex size-14 items-center justify-center rounded-full">
        <Icon className="size-7" />
      </div>
      <div className="text-fg mt-4 w-full truncate text-[14px] font-medium">{file.name}</div>
      <div className="text-muted mt-1 text-[12.5px]">No preview for this file type.</div>
      <a
        href={file.url}
        download={file.name}
        className="bg-brand text-on-brand hover:bg-brand-strong mt-5 inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-[12.5px] font-medium transition-colors"
      >
        <ArrowDownTrayIcon className="size-4" />
        Download
      </a>
    </div>
  )
}

function Body({ file }: { file: PreviewFile }) {
  const text = useText(file)

  if (file.kind === 'image') {
    return (
      <img
        src={file.url}
        alt={file.name}
        className="max-h-full max-w-full rounded-lg object-contain shadow-[0_20px_60px_rgba(0,0,0,0.35)]"
      />
    )
  }

  if (file.kind === 'pdf') {
    return (
      <iframe
        src={file.url}
        title={file.name}
        className="h-full w-full max-w-[1000px] rounded-2xl bg-white shadow-[0_20px_60px_rgba(0,0,0,0.35)]"
      />
    )
  }

  if (text.state === 'loading')
    return (
      <Shimmer tone="light" className="text-[14px] font-medium">
        Loading preview
      </Shimmer>
    )

  if (text.state === 'ready') return <TextBody text={text} />
  return <NoPreview file={file} />
}

function Thumb({
  file,
  active,
  onClick,
}: {
  file: PreviewFile
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
        <img src={file.url} alt="" className="size-full bg-white/10 object-cover" />
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
  files,
  start,
  onClose,
}: {
  files: PreviewFile[]
  start: number
  onClose: () => void
}) {
  const [index, setIndex] = useState(start)
  const shown = useEnterTransition(true)
  const file = files[index]
  const many = files.length > 1
  const step = (by: number) => setIndex((i) => (i + by + files.length) % files.length)

  useLayer(onClose)
  useWindowEvent('keydown', (e) => {
    if (many && e.key === 'ArrowLeft') step(-1)
    if (many && e.key === 'ArrowRight') step(1)
  })

  if (!file) throw new Error(`No file at ${index}`)

  const Icon = KIND_ICON[file.kind]

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={file.name}
      className={cn(
        'fixed inset-0 z-[100] flex flex-col bg-[#11181c]/88 backdrop-blur-sm transition-opacity duration-(--duration-medium)',
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
        <RoundButton label="Download" href={file.url} download={file.name}>
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
          key={index}
          className="animate-fade-in flex h-full w-full items-center justify-center"
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <Body file={file} />
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
            <Thumb key={i} file={f} active={i === index} onClick={() => setIndex(i)} />
          ))}
        </div>
      ) : null}
    </div>,
    document.body,
  )
}
