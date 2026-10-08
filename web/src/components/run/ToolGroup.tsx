import {
  ArchiveBoxArrowDownIcon,
  BellAlertIcon,
  BookOpenIcon,
  CalendarIcon,
  ChartBarIcon,
  ChevronRightIcon,
  ClockIcon,
  CircleStackIcon,
  CodeBracketSquareIcon,
  CommandLineIcon,
  DocumentPlusIcon,
  DocumentTextIcon,
  FolderIcon,
  MagnifyingGlassIcon,
  MapIcon,
  PencilSquareIcon,
  TicketIcon,
  UserIcon,
  UsersIcon,
  ChatBubbleLeftEllipsisIcon,
  CheckIcon,
  CheckCircleIcon,
  ArrowUpCircleIcon,
  ArrowsRightLeftIcon,
  MoonIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import type { Icon } from '@/components/ui'
import { memo, useEffect, useState } from 'react'
import type { ToolActivity } from '@shared/types.ts'
import { useSkeleton } from '@/components/skeletons'
import { reportError } from '@/components/Toasts'
import { CopyButton, Skeleton, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { prefetch, take } from '@/lib/prefetch'
import { cn } from '@/lib/cn'
import { useSettings } from '@/lib/settings'

const ICONS: Record<string, Icon> = {
  ov: CommandLineIcon,
  ov_sql: CircleStackIcon,
  ov_export: ArchiveBoxArrowDownIcon,
  ov_search: MagnifyingGlassIcon,
  ov_map: MapIcon,
  ov_case: TicketIcon,
  ws_list: FolderIcon,
  ws_search: MagnifyingGlassIcon,
  ws_read: CodeBracketSquareIcon,
  ws_edit: PencilSquareIcon,
  ws_write: DocumentPlusIcon,
  ws_run: CommandLineIcon,
  skill_read: BookOpenIcon,
  run_read: DocumentTextIcon,
  dd_logs: DocumentTextIcon,
  dd_metrics: ChartBarIcon,
  dd_monitors: BellAlertIcon,
  dd_events: CalendarIcon,
  dd_apm: ClockIcon,
  pd_incidents: BellAlertIcon,
  pd_incident: BellAlertIcon,
  pd_oncall: UserIcon,
  pd_directory: UsersIcon,
  pd_note: ChatBubbleLeftEllipsisIcon,
  pd_ack: CheckIcon,
  pd_resolve: CheckCircleIcon,
  pd_escalate: ArrowUpCircleIcon,
  pd_reassign: ArrowsRightLeftIcon,
  pd_snooze: MoonIcon,
}

const NOUNS: Record<string, [string, string]> = {
  ov: ['API call', 'API calls'],
  ov_sql: ['SQL query', 'SQL queries'],
  ov_export: ['export', 'exports'],
  ov_search: ['trackor search', 'trackor searches'],
  ov_map: ['map lookup', 'map lookups'],
  ov_case: ['case', 'cases'],
  ws_list: ['folder listing', 'folder listings'],
  ws_search: ['code search', 'code searches'],
  ws_read: ['file read', 'file reads'],
  ws_edit: ['edit', 'edits'],
  ws_write: ['new file', 'new files'],
  ws_run: ['command', 'commands'],
  skill_read: ['skill', 'skills'],
  run_read: ['file', 'files'],
  dd_logs: ['log search', 'log searches'],
  dd_metrics: ['metric query', 'metric queries'],
  dd_monitors: ['monitor check', 'monitor checks'],
  dd_events: ['event search', 'event searches'],
  dd_apm: ['APM query', 'APM queries'],
  pd_incidents: ['incident search', 'incident searches'],
  pd_incident: ['incident', 'incidents'],
  pd_oncall: ['on-call check', 'on-call checks'],
  pd_directory: ['directory lookup', 'directory lookups'],
  pd_note: ['incident note', 'incident notes'],
  pd_ack: ['acknowledge', 'acknowledges'],
  pd_resolve: ['resolve', 'resolves'],
  pd_escalate: ['escalation', 'escalations'],
  pd_reassign: ['reassignment', 'reassignments'],
  pd_snooze: ['snooze', 'snoozes'],
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

function readableInput(tool: ToolActivity): string {
  if (!tool.input) return ''

  try {
    const a = JSON.parse(tool.input) as Record<string, unknown>
    const at = a.instance ? `-- ${a.instance}\n` : ''
    const name = tool.name
    if (name === 'ov_sql') return `${at}${a.query}`
    if (name === 'pd_incident' || name === 'pd_ack' || name === 'pd_resolve')
      return String(a.incident)
    if (name === 'pd_note') return `${a.incident}\n${a.note}`
    if (name === 'pd_escalate') return `${a.incident} -> level ${a.level}`
    if (name === 'pd_snooze') return `${a.incident} for ${a.minutes} min`
    if (name === 'pd_reassign')
      return `${a.incident} -> ${a.policy ?? (a.users as string[] | undefined)?.join(', ')}`
    if (name.startsWith('dd_') || name.startsWith('pd_'))
      return [
        a.instance ? `instance: ${a.instance}` : '',
        a.query ? `query: ${a.query}` : '',
        a.mode ? `mode: ${a.mode}` : '',
        a.from ? `from: ${a.from}${a.to ? ` to ${a.to}` : ''}` : '',
        a.patterns ? 'grouped by message' : '',
      ]
        .filter(Boolean)
        .join('\n')
    if (name === 'ov')
      return `ov ${a.instance ? `-i ${a.instance} ` : ''}${(a.args as string[]).join(' ')}`
    if (name === 'ov_search')
      return `${a.trackor_type}: ${a.condition}\nfields: ${(a.fields as string[]).join(', ')}`
    if (name === 'ws_search')
      return `/${a.pattern}/${a.path ? `  in ${a.path}` : ''}${a.glob ? `  (${a.glob})` : ''}`
    if (name === 'ws_run') return `${a.cwd ? `${a.cwd}> ` : '> '}${a.command}`
    if (name === 'ws_edit') return `${a.path}\n--- old\n${a.old}\n+++ new\n${a.new}`
    if (name === 'ws_write') return `${a.path}\n${a.content}`
    if (name === 'ws_read' || name === 'ws_list' || name === 'run_read')
      return String(a.path ?? '.')
    return JSON.stringify(a, null, 2)
  } catch {
    return tool.input
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

const DETAIL_SLOT = 'tool'

function DetailSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-3 w-16" />
      <Skeleton className="h-16 w-full rounded-2xl" />
    </div>
  )
}

function ToolRow({ runId, tool }: { runId: string; tool: ToolActivity }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<Pick<ToolActivity, 'input' | 'output'>>()
  const lazy = Boolean(tool.lazy) && tool.input === undefined && tool.output === undefined
  const key = `${runId}:${tool.id}`
  const loading = useSkeleton(open && lazy && !detail)
  const full = lazy ? { ...tool, ...detail } : tool
  const Icon = ICONS[tool.name] ?? CommandLineIcon
  const input = readableInput(full)

  useEffect(() => {
    if (!open || !lazy || detail) return

    let stale = false
    take(DETAIL_SLOT, key, () => api.runDetails(runId, [tool.id], []))
      .then((d) => !stale && setDetail(d.tools[tool.id] ?? {}))
      .catch(reportError)
    return () => {
      stale = true
    }
  }, [open, lazy, detail, key, runId, tool.id])

  return (
    <div>
      <button
        type="button"
        onMouseEnter={() => {
          if (lazy && !detail)
            prefetch(DETAIL_SLOT, key, () => api.runDetails(runId, [tool.id], []))
        }}
        onClick={() => setOpen(!open)}
        className="hover:bg-raised flex w-full items-center gap-2 rounded-full px-2.5 py-1 text-left"
      >
        <ChevronRightIcon
          className={cn('text-faint size-3 shrink-0 transition-transform', open && 'rotate-90')}
        />
        {tool.status === 'running' ? (
          <Spinner className="text-brand size-3.5 shrink-0" />
        ) : tool.status === 'error' ? (
          <XMarkIcon className="text-danger size-3.5 shrink-0" />
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
        <div className="animate-fade-in mt-1 mb-2 ml-7 space-y-2">
          {lazy && !detail ? (
            loading ? (
              <DetailSkeleton />
            ) : null
          ) : (
            <>
              {input ? <Block title="Input" text={input} /> : null}
              {tool.status !== 'running' ? (
                <Block
                  title={tool.status === 'error' ? 'Error' : 'Output'}
                  text={full.output ?? ''}
                  error={tool.status === 'error'}
                />
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}

function sameTools(
  a: { runId: string; tools: ToolActivity[] },
  b: { runId: string; tools: ToolActivity[] },
): boolean {
  return (
    a.runId === b.runId &&
    a.tools.length === b.tools.length &&
    a.tools.every((t, i) => t === b.tools[i])
  )
}

export const ToolGroup = memo(function ToolGroup({
  runId,
  tools,
}: {
  runId: string
  tools: ToolActivity[]
}) {
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
        <ChevronRightIcon
          className={cn('text-faint size-3.5 shrink-0 transition-transform', open && 'rotate-90')}
        />
        {running ? <Spinner className="text-brand size-3.5 shrink-0" /> : null}
        <span className="min-w-0 truncate text-[12.5px]">
          {running ? (
            <span className="text-text">{running.label}</span>
          ) : (
            <span>
              {tools.length === 1 && tools[0].name === 'ov_case'
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
        <div className="border-line animate-fade-in mt-1 ml-1.5 border-l-2 pl-2">
          {tools.map((t) => (
            <ToolRow key={t.id} runId={runId} tool={t} />
          ))}
        </div>
      ) : null}
    </div>
  )
}, sameTools)
