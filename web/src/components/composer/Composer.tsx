import {
  ArrowUp as ArrowUpIcon,
  Paperclip as PaperClipIcon,
  Stop as StopIcon,
} from '@phosphor-icons/react'
import Document from '@tiptap/extension-document'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import { Placeholder, UndoRedo } from '@tiptap/extensions'
import { type Editor, EditorContent, useEditor } from '@tiptap/react'
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { notify, reportError } from '@/components/common/Toasts'
import { localFile, type PreviewFile } from '@/components/run/FilePreview'
import { cn } from '@/lib/cn'
import { useObjectUrls, useWindowEvent } from '@/lib/hooks'
import { isEditableTarget } from '@/lib/dom'
import { forgetDraft, loadFiles, loadText, saveFiles, saveText } from '@/lib/drafts'
import { withoutAttachments } from '@/lib/mentions'
import type { RefIndex } from '@/lib/references'
import { type Attached, Attachments, attachmentKey } from './Attachments'
import {
  atDocStart,
  docOf,
  lineContent,
  mentionNode,
  MentionNode,
  mentionRanges,
  mentionsIn,
  paragraphsOf,
  RefHighlight,
  textOf,
  type Trigger,
  triggerAt,
} from './editor'
import { type ChipFile, MentionFiles } from './MentionChip'
import {
  type ComposerCommand,
  ComposerMenu,
  type MenuItem,
  useMenuItems,
  useMentionGraph,
} from './menu'

const DRAFT_SAVE_MS = 300
const UNNAMED_PASTE = 'image.png'
const NO_COMMANDS: ComposerCommand[] = []
const NO_HISTORY: string[] = []
const NO_FILES: PreviewFile[] = []

export type ComposerKeyHandler = (e: KeyboardEvent, at: { start: boolean }) => boolean

function freeName(name: string, taken: Set<string>): string {
  if (!taken.has(name)) return name

  const dot = name.lastIndexOf('.')
  const stem = dot > 0 ? name.slice(0, dot) : name
  const ext = dot > 0 ? name.slice(dot) : ''
  let index = 2
  while (taken.has(`${stem}-${index}${ext}`)) index++

  return `${stem}-${index}${ext}`
}

function renamed(file: File, name: string): File {
  return name === file.name
    ? file
    : new File([file], name, { type: file.type, lastModified: file.lastModified })
}

function insertText(editor: Editor, text: string): void {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  editor
    .chain()
    .focus()
    .insertContent(lines.length === 1 ? lineContent(lines[0]) : paragraphsOf(lines.join('\n')))
    .run()
}

export function Composer({
  placeholder,
  onSend,
  onStop,
  busy,
  allowFiles,
  sentFiles = NO_FILES,
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
  commands = NO_COMMANDS,
  instance,
  runId,
  history = NO_HISTORY,
}: {
  placeholder: string
  onSend: (text: string, files: File[], alternate: boolean) => void | Promise<void>
  busyAction?: (alternate: boolean) => { label: string; icon: ReactNode }
  idleAction?: ReactNode
  onKeyDown?: ComposerKeyHandler
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
  commands?: ComposerCommand[]
  instance?: string
  runId?: string
  history?: string[]
}) {
  const [text, setText] = useState(() => loadText(draftKey))
  const [files, setFiles] = useState<File[]>([])
  const [alternate, setAlternate] = useState(false)
  const [trigger, setTrigger] = useState<Trigger>()
  const [dismissed, setDismissed] = useState<number>()
  const [active, setActive] = useState(0)
  const filesLoaded = useRef(false)
  const currentFiles = useRef<File[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const mentioned = useRef(new Set<string>())
  const trash = useRef(new Map<string, File>())
  const browsing = useRef<{ at: number; text: string } | undefined>(undefined)
  const latest = useRef<{
    key: (e: KeyboardEvent) => boolean
    paste: (e: ClipboardEvent) => boolean
    changed: (editor: Editor) => void
    placeholder: string
    refs?: RefIndex
  }>({ key: () => false, paste: () => false, changed: () => {}, placeholder })
  const urls = useObjectUrls(files)
  currentFiles.current = files
  const graph = useMentionGraph(instance)
  const attachedCount = files.length + sentFiles.length
  const canSend =
    (!busy || Boolean(queueWhileBusy)) &&
    (Boolean(allowEmpty) || text.trim().length > 0 || attachedCount > 0)
  const hasContent = text.trim().length > 0 || attachedCount > 0
  const showStop = busy && onStop && (submitLabel || !hasContent)
  const action = busy && hasContent ? busyAction?.(alternate) : undefined

  const editor = useEditor({
    extensions: [
      Document,
      Paragraph,
      Text,
      UndoRedo,
      Placeholder.configure({ placeholder: () => latest.current.placeholder }),
      MentionNode,
      RefHighlight.configure({ index: () => latest.current.refs }),
    ],
    content: docOf(text),
    autofocus: autoFocus ? 'end' : false,
    editorProps: {
      attributes: {
        class: cn(
          'composer-editor px-4 text-[14px] outline-none',
          size === 'lg' ? 'min-h-[72px] pt-3.5 pb-2' : 'min-h-[60px] pt-3 pb-1.5',
        ),
        role: 'textbox',
        'aria-multiline': 'true',
      },
      handleKeyDown: (_view, e) => latest.current.key(e),
      handlePaste: (_view, e) => latest.current.paste(e),
      handleDrop: (_view, e) => Boolean(e.dataTransfer?.files.length),
      clipboardTextSerializer: (slice) => textOf(slice.content),
    },
    onUpdate: ({ editor: changed }) => latest.current.changed(changed),
    onSelectionUpdate: ({ editor: moved }) => setTrigger(triggerAt(moved.state)),
  })

  const items = useMenuItems(trigger, {
    commands,
    attachments: [...sentFiles.map((f) => f.name), ...files.map((f) => f.name)],
    graph,
    runId,
  })
  const menuOpen = Boolean(trigger && trigger.from !== dismissed && items.length)

  latest.current.placeholder = placeholder
  latest.current.refs = graph?.refs

  useEffect(() => {
    editor.view.dispatch(editor.state.tr)
  }, [editor, placeholder, graph])

  useEffect(() => setActive(0), [trigger?.char, trigger?.command, trigger?.query])

  const replaceDoc = useCallback(
    (value: string, focus: 'start' | 'end' | false) => {
      editor.commands.setContent(docOf(value), { emitUpdate: false })
      mentioned.current = mentionsIn(editor.state.doc, 'attachment')
      const shown = textOf(editor.state.doc.content)
      setText(shown)
      setTrigger(undefined)
      if (focus) editor.commands.focus(focus)
      return shown
    },
    [editor],
  )

  useEffect(() => {
    let alive = true
    filesLoaded.current = false
    browsing.current = undefined
    trash.current.clear()
    replaceDoc(loadText(draftKey), false)

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

  useWindowEvent('beforeunload', () => saveText(draftKey, textOf(editor.state.doc.content)))
  useWindowEvent('keydown', (e) => setAlternate(e.ctrlKey || e.metaKey))
  useWindowEvent('keyup', (e) => setAlternate(e.ctrlKey || e.metaKey))
  useWindowEvent('blur', () => setAlternate(false))

  const send = async (alternate = false) => {
    if (!canSend) return

    const value = text.trim()
    const attached = files

    replaceDoc('', false)
    setFiles([])
    trash.current.clear()
    browsing.current = undefined

    try {
      await onSend(value, attached, alternate)
      forgetDraft(draftKey)
    } catch {
      replaceDoc(value, 'end')
      setFiles(attached)
    }
  }

  useEffect(() => {
    if (draft) replaceDoc(draft.text, 'end')
  }, [draft?.at])

  const addFiles = (list: FileList | File[] | null) => {
    if (!allowFiles || !list?.length) return

    const present = [...currentFiles.current, ...sentFiles]
    const same = new Set(present.map((f) => attachmentKey(f.name, f.size)))
    const names = new Set(present.map((f) => f.name))
    const fresh: File[] = []
    const repeated: string[] = []
    for (const file of Array.from(list)) {
      const key = attachmentKey(file.name, file.size)
      if (same.has(key)) {
        repeated.push(file.name)
        continue
      }

      const named = renamed(file, freeName(file.name, names))
      same.add(key)
      names.add(named.name)
      fresh.push(named)
    }

    if (repeated.length) notify(`Already attached: ${repeated.join(', ')}`)
    if (!fresh.length) return

    currentFiles.current = [...currentFiles.current, ...fresh]
    setFiles((current) => [...current, ...fresh])
    editor
      .chain()
      .focus()
      .insertContent(
        fresh.flatMap((file) => [
          mentionNode({ kind: 'attachment', target: file.name, label: file.name }),
          { type: 'text', text: ' ' },
        ]),
      )
      .run()
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

  const detach = (names: string[]) => {
    const local = files.filter((f) => names.includes(f.name))
    for (const file of local) trash.current.set(file.name, file)
    if (local.length) setFiles((current) => current.filter((f) => !local.includes(f)))

    for (const name of names) if (sentFiles.some((f) => f.name === name)) onRemoveSentFile?.(name)
  }

  const removeAttachment = (name: string, direct: () => void) => {
    const ranges = mentionRanges(editor.state.doc, 'attachment', name)
    if (!ranges.length) {
      direct()
      return
    }

    editor
      .chain()
      .command(({ tr }) => {
        for (const [from, to] of ranges.reverse()) tr.delete(from, to)
        return true
      })
      .run()
  }

  const pick = (item: MenuItem) => {
    if (!trigger) return

    const range = { from: trigger.from, to: trigger.to }
    const chain = editor.chain().focus()
    const { action: picked } = item
    if (picked.type === 'mention') {
      chain.insertContentAt(range, [mentionNode(picked.mention), { type: 'text', text: ' ' }]).run()
      return
    }

    if (picked.type === 'command' && picked.command.options) {
      chain.insertContentAt(range, `/${picked.command.name} `).run()
      return
    }

    chain.deleteRange(range).run()
    const value = picked.type === 'option' ? picked.value : undefined
    void Promise.resolve(picked.command.run(value)).catch(reportError)
  }

  const browse = (step: -1 | 1): boolean => {
    const current = browsing.current
    const unchanged = current !== undefined && current.text === text
    if (step === -1 && !unchanged && (current !== undefined || text.trim())) return false
    if (step === 1 && !unchanged) return false

    const next = (current?.at ?? history.length) + step
    if (next < 0) return true

    if (next >= history.length) {
      browsing.current = undefined
      replaceDoc('', 'end')
      return true
    }

    browsing.current = { at: next, text: replaceDoc(withoutAttachments(history[next]), 'end') }
    return true
  }

  const menuKey = (e: KeyboardEvent): boolean => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((current) => (current + step + items.length) % items.length)
      return true
    }

    if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
      pick(items[active] ?? items[0])
      return true
    }

    if (e.key !== 'Escape') return false

    e.stopPropagation()
    setDismissed(trigger?.from)
    return true
  }

  latest.current.key = (e) => {
    if (e.isComposing) return false
    if (menuOpen && menuKey(e)) return true
    if (onKeyDown?.(e, { start: atDocStart(editor.state) })) return true

    const plain = !e.altKey && !e.shiftKey && !e.ctrlKey && !e.metaKey
    if (plain && history.length && e.key === 'ArrowUp' && browse(-1)) return true
    if (plain && e.key === 'ArrowDown' && browse(1)) return true

    if (e.key !== 'Enter') return false
    if (e.shiftKey) return editor.commands.splitBlock()

    void send(e.ctrlKey || e.metaKey)
    return true
  }

  latest.current.paste = (e) => {
    const tookFiles = takeClipboardFiles(e.clipboardData)
    const pasted = e.clipboardData?.getData('text/plain') ?? ''
    if (!pasted) return tookFiles

    insertText(editor, pasted)
    return true
  }

  latest.current.changed = (changed) => {
    const doc = changed.state.doc
    setText(textOf(doc.content))
    setTrigger(triggerAt(changed.state))

    const now = mentionsIn(doc, 'attachment')
    const gone = [...mentioned.current].filter((name) => !now.has(name))
    const back = [...now].filter((name) => !mentioned.current.has(name) && trash.current.has(name))
    mentioned.current = now

    if (gone.length) detach(gone)
    if (!back.length) return

    const restored = back.flatMap((name) => trash.current.get(name) ?? [])
    for (const name of back) trash.current.delete(name)
    setFiles((current) => [...current, ...restored])
  }

  useWindowEvent('paste', (e) => {
    if (e.defaultPrevented || isEditableTarget(e.target)) return
    if (!takeClipboardFiles(e.clipboardData)) return
    e.preventDefault()
  })

  const fileFor = (name: string): ChipFile | undefined => {
    const sent = sentFiles.find((f) => f.name === name)
    if (sent) return { size: sent.size, url: sent.kind === 'image' ? sent.url : undefined }

    const local = files.find((f) => f.name === name)
    return local ? { size: local.size, url: urls.get(local) } : undefined
  }

  const attachments: Attached[] = [
    ...sentFiles.map((file) => ({
      key: `sent:${file.name}`,
      file,
      onRemove: () => removeAttachment(file.name, () => onRemoveSentFile?.(file.name)),
    })),
    ...files.flatMap((file) => {
      const url = urls.get(file)
      if (!url) return []

      return [
        {
          key: url,
          file: localFile(file, url),
          onRemove: () =>
            removeAttachment(file.name, () =>
              setFiles((current) => current.filter((f) => f !== file)),
            ),
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
      className="border-line-strong focus-within:border-brand relative rounded-[26px] border bg-white shadow-[0_2px_12px_rgba(38,50,56,0.06)] transition-colors"
    >
      {menuOpen ? (
        <ComposerMenu items={items} active={active} onPick={pick} onHover={setActive} />
      ) : null}
      <Attachments items={attachments} />
      <MentionFiles.Provider value={fileFor}>
        <EditorContent editor={editor} className="max-h-60 scrollbar-thin overflow-y-auto" />
      </MentionFiles.Provider>
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
