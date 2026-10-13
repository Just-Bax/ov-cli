import {
  ArrowsClockwise as ArrowPathIcon,
  Check as CheckIcon,
  CaretRight as ChevronRightIcon,
  File as DocumentIcon,
  Folder as FolderIcon,
  FolderOpen as FolderOpenIcon,
  Sparkle as SparklesIcon,
} from '@phosphor-icons/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { WorkspaceEntry } from '@shared/types.ts'
import { dialog } from '@/components/Dialog'
import { CodeSkeleton, TreeRowsSkeleton, useSkeleton } from '@/components/skeletons'
import { reportError } from '@/components/Toasts'
import { Button, EmptyState, IconBadge, Page, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useUnsavedWarning } from '@/lib/unsaved'
import { cn } from '@/lib/cn'
import { openDraft } from '@/lib/draft'
import { languageOf } from '@/lib/languages'
import { monaco } from '@/lib/monaco'
import { href } from '@/lib/route'
import { useSettings } from '@/lib/settings'

const INDENT_PX = 14

type Open = { path: string; saved: string }

function Folder({
  path,
  depth,
  active,
  onOpen,
  version,
}: {
  path: string
  depth: number
  active?: string
  onOpen: (path: string) => void
  version: number
}) {
  const [entries, setEntries] = useState<WorkspaceEntry[]>()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const showSkeleton = useSkeleton(!entries)

  useEffect(() => {
    api
      .workspaceEntries(path)
      .then((r) => setEntries(r.entries))
      .catch(reportError)
  }, [path, version])

  if (showSkeleton || !entries)
    return showSkeleton ? (
      <TreeRowsSkeleton rows={depth ? 3 : 14} indent={depth * INDENT_PX} />
    ) : null

  const toggle = (p: string) =>
    setExpanded((all) => {
      const next = new Set(all)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })

  return (
    <>
      {entries.map((e) => {
        const open = expanded.has(e.path)
        const Icon = e.dir ? (open ? FolderOpenIcon : FolderIcon) : DocumentIcon

        return (
          <div key={e.path}>
            <button
              type="button"
              title={e.path}
              onClick={() => (e.dir ? toggle(e.path) : onOpen(e.path))}
              className={cn(
                'flex h-7 w-full items-center gap-1.5 rounded-full pr-3 text-left text-[12.5px] transition-colors',
                active === e.path ? 'bg-brand-soft text-brand-strong' : 'text-text hover:bg-raised',
              )}
              style={{ paddingLeft: depth * INDENT_PX + 8 }}
            >
              <ChevronRightIcon
                className={cn(
                  'text-faint size-3 shrink-0 transition-transform',
                  open && 'rotate-90',
                  !e.dir && 'invisible',
                )}
              />
              <Icon className={cn('size-3.5 shrink-0', e.dir ? 'text-brand' : 'text-faint')} />
              <span className="truncate">{e.name}</span>
            </button>
            {e.dir && open ? (
              <Folder
                path={e.path}
                depth={depth + 1}
                active={active}
                onOpen={onOpen}
                version={version}
              />
            ) : null}
          </div>
        )
      })}
      {!entries.length ? (
        <div
          className="text-faint py-1 text-[12px]"
          style={{ paddingLeft: depth * INDENT_PX + 30 }}
        >
          Empty
        </div>
      ) : null}
    </>
  )
}

function Editor({ file, onChange }: { file: Open; onChange: (text: string) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const editor = useRef<monaco.editor.IStandaloneCodeEditor>(undefined)
  const changed = useRef(onChange)
  changed.current = onChange

  useEffect(() => {
    if (!host.current) return

    const created = monaco.editor.create(host.current, {
      theme: 'ov-light',
      automaticLayout: true,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      fontSize: 12.5,
      lineHeight: 21,
      minimap: { enabled: true, renderCharacters: false },
      scrollBeyondLastLine: false,
      padding: { top: 12, bottom: 12 },
      stickyScroll: { enabled: true },
      fixedOverflowWidgets: true,
    })
    created.onDidChangeModelContent(() => changed.current(created.getValue()))
    editor.current = created

    return () => {
      created.getModel()?.dispose()
      created.dispose()
    }
  }, [])

  useEffect(() => {
    const current = editor.current
    if (!current) return

    const previous = current.getModel()
    current.setModel(monaco.editor.createModel(file.saved, languageOf(file.path)))
    previous?.dispose()
  }, [file.path, file.saved])

  return <div ref={host} className="h-full w-full" />
}

export function WorkspacePage() {
  const { settings } = useSettings()
  const [open, setOpen] = useState<Open>()
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [version, setVersion] = useState(0)
  const dirty = Boolean(open && text !== open.saved)
  useUnsavedWarning(dirty)
  const showEditorSkeleton = useSkeleton(loading)

  const load = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const file = await api.workspaceFile(path)
      setOpen({ path, saved: file.content })
      setText(file.content)
    } catch (e) {
      reportError(e)
    } finally {
      setLoading(false)
    }
  }, [])

  const choose = async (path: string) => {
    if (dirty) {
      const ok = await dialog.confirm({
        title: 'Discard unsaved changes?',
        body: `${open?.path} has changes that are not saved.`,
        confirmLabel: 'Discard',
        tone: 'danger',
      })
      if (!ok) return
    }
    void load(path)
  }

  const save = useCallback(async () => {
    if (!open || !dirty) return

    setSaving(true)
    try {
      const file = await api.saveWorkspaceFile(open.path, text)
      setOpen({ path: open.path, saved: file.content })
    } catch (e) {
      reportError(e)
    } finally {
      setSaving(false)
    }
  }, [open, dirty, text])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void save()
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [save])

  if (!settings.workspace)
    return (
      <Page title="Workspace">
        <div className="flex h-full items-center justify-center p-6">
          <EmptyState
            badge={<IconBadge icon={FolderIcon} size="lg" />}
            title="Pick a workspace"
            action={
              <a href={href({ page: 'settings' })}>
                <Button variant="primary">Open Settings</Button>
              </a>
            }
          >
            Choose the folder with your code in Settings &gt; Workspace. The agent works inside it,
            and you can browse and edit it here.
          </EmptyState>
        </div>
      </Page>
    )

  const ask = () =>
    openDraft({
      prompt: open
        ? `In the workspace file ${open.path}: `
        : `In the workspace ${settings.workspace}: `,
    })

  const actions = (
    <>
      <Button
        variant="ghost"
        className="aspect-square px-0"
        aria-label="Reload"
        onClick={() => setVersion((v) => v + 1)}
      >
        <ArrowPathIcon className="size-3.5" />
      </Button>
      {open ? (
        <Button variant="secondary" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? <Spinner className="size-3.5" /> : <CheckIcon className="size-3.5" />} Save
        </Button>
      ) : null}
      <Button variant="primary" onClick={ask}>
        <SparklesIcon className="size-3.5" /> Ask the agent
      </Button>
    </>
  )

  return (
    <Page
      title="Workspace"
      subtitle={
        <span className="truncate font-mono">
          {open
            ? `${settings.workspace} / ${open.path}${dirty ? ' (unsaved)' : ''}`
            : settings.workspace}
        </span>
      }
      actions={actions}
    >
      <div className="flex h-full min-h-[480px]">
        <div className="border-line-strong/60 w-[300px] shrink-0 scrollbar-thin overflow-y-auto border-r p-2">
          <Folder
            path=""
            depth={0}
            active={open?.path}
            onOpen={(p) => void choose(p)}
            version={version}
          />
        </div>
        <div className="relative min-w-0 flex-1">
          {open ? (
            <Editor file={open} onChange={setText} />
          ) : (
            <div className="text-muted flex h-full items-center justify-center text-[13px]">
              Pick a file on the left. Edit it here and save with Ctrl+S.
            </div>
          )}
          {showEditorSkeleton ? (
            <div className="absolute inset-0 bg-white">
              <CodeSkeleton />
            </div>
          ) : null}
        </div>
      </div>
    </Page>
  )
}
