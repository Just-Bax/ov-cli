import {
  ChevronRight,
  Database,
  FileCode,
  FileText,
  GitBranch,
  type LucideIcon,
  Search,
  Terminal,
  Ticket,
  X,
} from 'lucide-react'
import { useState } from 'react'
import type { ToolActivity } from '@shared/types.ts'
import { CopyButton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useSettings } from '@/lib/settings'

const ICONS: Record<string, LucideIcon> = {
  sql: Database,
  ov: Terminal,
  trackor_search: Search,
  source_search: Search,
  source_read: FileCode,
  read_file: FileText,
  git_clone: GitBranch,
  load_case: Ticket,
}

const NOUNS: Record<string, [string, string]> = {
  sql: ['SQL query', 'SQL queries'],
  ov: ['API call', 'API calls'],
  trackor_search: ['trackor search', 'trackor searches'],
  source_search: ['code search', 'code searches'],
  source_read: ['source file', 'source files'],
  read_file: ['file', 'files'],
  git_clone: ['repo', 'repos'],
  load_case: ['case', 'cases'],
}

function summarize(tools: ToolActivity[]): string {
  const counts = new Map<string, number>()
  for (const t of tools) counts.set(t.name, (counts.get(t.name) ?? 0) + 1)
  return [...counts]
    .map(([name, n]) => {
      const [one, many] = NOUNS[name] ?? [name, name]
      return `${n} ${n === 1 ? one : many}`
    })
    .join(', ')
}

/** Show tool input the way a person would write it, not as raw JSON. */
function readableInput(tool: ToolActivity): { text: string; lang: string } {
  if (!tool.input) return { text: '', lang: 'text' }
  try {
    const a = JSON.parse(tool.input) as Record<string, unknown>
    const at = a.instance ? `-- ${a.instance}\n` : ''
    if (tool.name === 'sql') return { text: `${at}${a.query}`, lang: 'sql' }
    if (tool.name === 'ov')
      return {
        text: `ov ${a.instance ? `-i ${a.instance} ` : ''}${(a.args as string[]).join(' ')}`,
        lang: 'shell',
      }
    if (tool.name === 'trackor_search')
      return {
        text: `${a.trackor_type}: ${a.condition}\nfields: ${(a.fields as string[]).join(', ')}`,
        lang: 'text',
      }
    if (tool.name === 'source_search')
      return { text: `${a.source}: /${a.pattern}/${a.path ? `  in ${a.path}` : ''}`, lang: 'text' }
    if (tool.name === 'source_read' || tool.name === 'read_file')
      return { text: `${a.source ? `${a.source}/` : ''}${a.path}`, lang: 'text' }
    if (tool.name === 'git_clone') return { text: String(a.url), lang: 'text' }
    return { text: JSON.stringify(a, null, 2), lang: 'json' }
  } catch {
    return { text: tool.input, lang: 'text' }
  }
}

function Block({ title, text, error }: { title: string; text: string; error?: boolean }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-faint text-[11px] font-medium">{title}</span>
        {text ? <CopyButton text={text} variant="ghost" /> : null}
      </div>
      <pre
        className={cn(
          'max-h-64 scrollbar-thin overflow-auto rounded-2xl px-3 py-2 font-mono text-[11.5px] leading-[18px] break-all whitespace-pre-wrap',
          error ? 'bg-danger-soft/60 text-danger' : 'bg-raised text-fg',
        )}
      >
        {text || '(empty)'}
      </pre>
    </div>
  )
}

function ToolRow({ tool }: { tool: ToolActivity }) {
  const [open, setOpen] = useState(false)
  const Icon = ICONS[tool.name] ?? Terminal
  const input = readableInput(tool)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="hover:bg-raised flex w-full items-center gap-2 rounded-full px-2.5 py-1 text-left"
      >
        <ChevronRight
          className={cn('text-faint size-3 shrink-0 transition-transform', open && 'rotate-90')}
        />
        {tool.status === 'running' ? (
          <Spinner className="text-brand size-3.5 shrink-0" />
        ) : tool.status === 'error' ? (
          <X className="text-danger size-3.5 shrink-0" />
        ) : (
          <Icon className="text-muted size-3.5 shrink-0" />
        )}
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-[12.5px]',
            tool.status === 'error' ? 'text-danger' : 'text-text',
          )}
        >
          {tool.label}
        </span>
        {tool.ms !== undefined ? (
          <span className="text-faint shrink-0 text-[11px]">{(tool.ms / 1000).toFixed(1)}s</span>
        ) : null}
      </button>
      {open ? (
        <div className="mt-1 mb-2 ml-7 space-y-2">
          {input.text ? <Block title="Input" text={input.text} /> : null}
          {tool.status !== 'running' ? (
            <Block
              title={tool.status === 'error' ? 'Error' : 'Output'}
              text={tool.output ?? ''}
              error={tool.status === 'error'}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function ToolGroup({ tools }: { tools: ToolActivity[] }) {
  const running = tools.find((t) => t.status === 'running')
  const failed = tools.filter((t) => t.status === 'error').length
  const [open, setOpen] = useState(useSettings().settings.expandTools)
  const total = tools.reduce((s, t) => s + (t.ms ?? 0), 0)

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-muted hover:text-fg hover:bg-raised -ml-2 flex max-w-full items-center gap-1.5 rounded-full px-2 py-1 text-left"
      >
        <ChevronRight
          className={cn('text-faint size-3.5 shrink-0 transition-transform', open && 'rotate-90')}
        />
        {running ? <Spinner className="text-brand size-3.5 shrink-0" /> : null}
        <span className="min-w-0 truncate text-[12.5px]">
          {running ? (
            <span className="text-text">{running.label}</span>
          ) : (
            <span>
              {tools.length === 1 && tools[0].name === 'load_case'
                ? tools[0].label
                : summarize(tools)}
            </span>
          )}
        </span>
        {failed ? <span className="text-danger shrink-0 text-[11px]">{failed} failed</span> : null}
        {!running && total ? (
          <span className="text-faint shrink-0 text-[11px]">{(total / 1000).toFixed(1)}s</span>
        ) : null}
      </button>
      {open ? (
        <div className="border-line mt-1 ml-1.5 border-l-2 pl-2">
          {tools.map((t) => (
            <ToolRow key={t.id} tool={t} />
          ))}
        </div>
      ) : null}
    </div>
  )
}
