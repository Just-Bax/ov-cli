import {
  DownloadSimple as ArrowDownTrayIcon,
  ChatsCircle as ChatBubbleLeftRightIcon,
  Code as CodeBracketIcon,
  GearSix as Cog6ToothIcon,
  TerminalWindow as CommandLineIcon,
  Folder as FolderIcon,
  Heartbeat as HeartIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
  MapTrifold as MapIcon,
  Plus as PlusIcon,
  Stop as StopIcon,
  SidebarSimple as ViewColumnsIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '@shared/types.ts'
import { runActions } from '@/components/RunMenu'
import { reportError } from '@/components/Toasts'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { openDraft } from '@/lib/draft'
import { go, type Route } from '@/lib/route'
import { useRuns } from '@/lib/runs'
import { layerOpen, useLayer } from '@/lib/layers'
import { canUndo, runUndo } from '@/lib/undo'

const MAX_THREADS = 30
const THREAD_JUMPS = 9
export const TOGGLE_SIDEBAR = 'ov-agent:toggle-sidebar'
export const OPEN_FIND = 'ov-agent:find'

type Command = {
  id: string
  group: 'Actions' | 'This thread' | 'Threads' | 'Go to'
  label: string
  hint?: string
  keys?: string
  icon: ReactNode
  run: () => void
}

export const SHORTCUTS: [string, string][] = [
  ['Ctrl+K', 'Command palette'],
  ['Alt+N', 'New run'],
  ['Alt+1 to Alt+9', 'Open a thread from the sidebar'],
  ['Ctrl+B', 'Collapse or expand the sidebar'],
  ['Ctrl+F', 'Find in this thread'],
  ['Alt+S', 'Stop the agent in this thread'],
  ['Ctrl+Enter', 'Send the other way: steer or queue'],
  ['Ctrl+Z', 'Undo settle, pin or snooze'],
  ['?', 'Show these shortcuts'],
]

function editable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return Boolean(
    el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable),
  )
}

const WORKING = new Set(['queued', 'running', 'waiting'])

function sidebarOrder(runs: RunSummary[]): RunSummary[] {
  const rest = runs.filter((r) => !r.pinned)
  return [
    ...runs.filter((r) => r.pinned),
    ...rest.filter((r) => WORKING.has(r.status)),
    ...rest.filter((r) => !WORKING.has(r.status)),
  ]
}

function matches(command: Command, words: string[]): boolean {
  const text = `${command.label} ${command.hint ?? ''} ${command.group}`.toLowerCase()
  return words.every((w) => text.includes(w))
}

export function CommandPalette({ route }: { route: Route }) {
  const [open, setOpen] = useState(false)
  const [help, setHelp] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const list = useRuns()
  const input = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const runId = route.page === 'run' ? route.id : undefined

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.defaultPrevented) return
      const command = e.ctrlKey || e.metaKey
      const inEditor = (e.target as HTMLElement | null)?.closest?.('.monaco-editor')
      if (command && !e.shiftKey && !e.altKey && e.code === 'KeyK' && !inEditor) {
        if (layerOpen() && !open) return
        e.preventDefault()
        setHelp(false)
        setOpen((v) => !v)
        return
      }
      if (layerOpen() || editable(e.target)) return
      if (command && !e.shiftKey && !e.altKey && e.code === 'KeyZ' && canUndo()) {
        e.preventDefault()
        runUndo()
        return
      }
      if (command && !e.shiftKey && !e.altKey && e.code === 'KeyB') {
        e.preventDefault()
        window.dispatchEvent(new Event(TOGGLE_SIDEBAR))
        return
      }
      if (e.altKey && !command && !e.shiftKey) {
        const digit = /^Digit([1-9])$/.exec(e.code)
        if (e.code === 'KeyN') {
          e.preventDefault()
          go({ page: 'home' })
        } else if (e.code === 'KeyS' && runId) {
          e.preventDefault()
          void api.cancel(runId).catch(reportError)
        } else if (digit) {
          const target = sidebarOrder(list?.active ?? [])[Number(digit[1]) - 1]
          if (target) {
            e.preventDefault()
            go({ page: 'run', id: target.id })
          }
        }
        return
      }
      if (e.key === '?') {
        e.preventDefault()
        setOpen(false)
        setHelp((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [runId, list, open])

  useLayer(() => setOpen(false), open)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)
    requestAnimationFrame(() => input.current?.focus())
  }, [open])

  const commands = useMemo(() => {
    const all = [...(list?.active ?? []), ...(list?.snoozed ?? []), ...(list?.settled ?? [])]
    const current = all.find((r) => r.id === runId)
    const settledIds = new Set((list?.settled ?? []).map((r) => r.id))
    const out: Command[] = [
      {
        id: 'new',
        group: 'Actions',
        label: 'New run',
        keys: 'Alt+N',
        icon: <PlusIcon className="size-4" />,
        run: () => go({ page: 'home' }),
      },
      {
        id: 'sidebar',
        group: 'Actions',
        label: 'Collapse or expand the sidebar',
        keys: 'Ctrl+B',
        icon: <ViewColumnsIcon className="size-4" />,
        run: () => window.dispatchEvent(new Event(TOGGLE_SIDEBAR)),
      },
      {
        id: 'shortcuts',
        group: 'Actions',
        label: 'Keyboard shortcuts',
        keys: '?',
        icon: <CommandLineIcon className="size-4" />,
        run: () => setHelp(true),
      },
    ]

    if (current) {
      out.push(
        {
          id: 'find',
          group: 'This thread',
          label: 'Find in thread',
          keys: 'Ctrl+F',
          icon: <MagnifyingGlassIcon className="size-4" />,
          run: () => window.dispatchEvent(new Event(OPEN_FIND)),
        },
        {
          id: 'export',
          group: 'This thread',
          label: 'Export as Markdown',
          icon: <ArrowDownTrayIcon className="size-4" />,
          run: () => window.location.assign(api.exportUrl(current.id)),
        },
      )
      if (WORKING.has(current.status))
        out.push({
          id: 'stop',
          group: 'This thread',
          label: 'Stop the agent',
          keys: 'Alt+S',
          icon: <StopIcon className="size-4" />,
          run: () => void api.cancel(current.id).catch(reportError),
        })
      for (const action of runActions(current, settledIds.has(current.id)))
        out.push({
          id: `act-${action.label}`,
          group: 'This thread',
          label: action.label,
          icon: action.icon,
          run: () => void Promise.resolve(action.run()).catch(reportError),
        })
    }

    const pages: [Route, string, ReactNode][] = [
      [{ page: 'map' }, 'Instance map', <MapIcon key="m" className="size-4" />],
      [{ page: 'explorer' }, 'Explorer', <CodeBracketIcon key="e" className="size-4" />],
      [{ page: 'health' }, 'Health', <HeartIcon key="h" className="size-4" />],
      [{ page: 'workspace' }, 'Workspace', <FolderIcon key="w" className="size-4" />],
      [{ page: 'settings' }, 'Settings', <Cog6ToothIcon key="s" className="size-4" />],
    ]
    for (const [target, label, icon] of pages)
      out.push({ id: `go-${label}`, group: 'Go to', label, icon, run: () => go(target) })

    const order = sidebarOrder(list?.active ?? [])
    for (const r of [...order, ...(list?.snoozed ?? []), ...(list?.settled ?? [])].slice(
      0,
      MAX_THREADS * 4,
    )) {
      const jump = order.indexOf(r)
      out.push({
        id: `run-${r.id}`,
        group: 'Threads',
        label: r.title,
        hint: settledIds.has(r.id) ? 'settled' : r.snoozedUntil ? 'snoozed' : r.instance,
        keys: jump >= 0 && jump < THREAD_JUMPS ? `Alt+${jump + 1}` : undefined,
        icon: <ChatBubbleLeftRightIcon className="size-4" />,
        run: () => go({ page: 'run', id: r.id }),
      })
    }
    return out
  }, [list, runId])

  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = commands.filter((c) => matches(c, words))
  const visible = [
    ...shown.filter((c) => c.group !== 'Threads'),
    ...shown.filter((c) => c.group === 'Threads').slice(0, MAX_THREADS),
  ]
  if (query.trim())
    visible.push({
      id: 'draft',
      group: 'Actions',
      label: `New run: ${query.trim()}`,
      hint: 'opens it in the composer',
      icon: <PlusIcon className="size-4" />,
      run: () => openDraft({ prompt: query.trim() }),
    })

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const choose = (command?: Command) => {
    if (!command) return
    setOpen(false)
    command.run()
  }

  if (help) return <ShortcutsDialog onClose={() => setHelp(false)} />
  if (!open) return null

  let group = ''
  return createPortal(
    <div
      className="fixed inset-0 z-[150] flex items-start justify-center bg-[#263238]/25 px-4 pt-[12vh] backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}
    >
      <div
        role="dialog"
        aria-label="Command palette"
        className="animate-pop w-full max-w-[600px] overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(38,50,56,0.28)]"
      >
        <div className="border-line flex h-14 items-center gap-3 border-b px-4">
          <MagnifyingGlassIcon className="text-faint size-5 shrink-0" />
          <input
            ref={input}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((i) => Math.min(visible.length - 1, i + 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((i) => Math.max(0, i - 1))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                choose(visible[active])
              }
            }}
            placeholder="Search threads and actions, or type a new question"
            className="placeholder:text-faint text-fg flex-1 bg-transparent text-[14.5px] outline-none"
          />
          <kbd className="text-faint border-line rounded-md border px-1.5 text-[11px]">Esc</kbd>
        </div>
        <div ref={listRef} className="max-h-[56vh] scrollbar-thin overflow-y-auto p-2">
          {visible.map((c, i) => {
            const header = c.group !== group ? (group = c.group) : undefined
            return (
              <div key={c.id}>
                {header ? (
                  <div className="text-faint px-3 pt-2 pb-1 text-[11px] font-medium">{header}</div>
                ) : null}
                <button
                  type="button"
                  data-index={i}
                  onMouseMove={() => setActive(i)}
                  onClick={() => choose(c)}
                  className={cn(
                    'flex h-9 w-full items-center gap-3 rounded-xl px-3 text-left text-[13px]',
                    i === active ? 'bg-brand-soft text-brand-strong' : 'text-fg',
                  )}
                >
                  <span className={i === active ? 'text-brand-strong' : 'text-muted'}>
                    {c.icon}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{c.label}</span>
                  {c.hint ? (
                    <span className="text-faint shrink-0 text-[11.5px]">{c.hint}</span>
                  ) : null}
                  {c.keys ? (
                    <kbd className="text-faint border-line shrink-0 rounded-md border px-1.5 text-[11px]">
                      {c.keys}
                    </kbd>
                  ) : null}
                </button>
              </div>
            )
          })}
          {!visible.length ? (
            <div className="text-faint px-3 py-6 text-center text-[12.5px]">Nothing matches.</div>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}

function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  useLayer(onClose)

  return createPortal(
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-[#263238]/25 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-label="Keyboard shortcuts"
        className="animate-pop w-full max-w-[440px] rounded-2xl bg-white p-5 shadow-[0_20px_60px_rgba(38,50,56,0.28)]"
      >
        <div className="text-fg mb-3 text-[15px] font-semibold">Keyboard shortcuts</div>
        <div className="divide-line divide-y">
          {SHORTCUTS.map(([keys, what]) => (
            <div key={keys} className="flex items-center justify-between gap-4 py-2 text-[13px]">
              <span className="text-text">{what}</span>
              <kbd className="text-muted border-line bg-raised rounded-md border px-2 text-[11.5px]">
                {keys}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  )
}
