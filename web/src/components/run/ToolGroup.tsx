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
  DocumentTextIcon,
  MagnifyingGlassIcon,
  MapIcon,
  ShareIcon,
  TicketIcon,
  UserIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import type { Icon } from '@/components/ui'
import { useState } from 'react'
import type { ToolActivity } from '@shared/types.ts'
import { CopyButton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useSettings } from '@/lib/settings'

const ICONS: Record<string, Icon> = {
  ov: CommandLineIcon,
  ov_sql: CircleStackIcon,
  ov_export: ArchiveBoxArrowDownIcon,
  ov_search: MagnifyingGlassIcon,
  ov_map: MapIcon,
  ov_case: TicketIcon,
  source_search: MagnifyingGlassIcon,
  source_read: CodeBracketSquareIcon,
  github_clone: ShareIcon,
  read_skill: BookOpenIcon,
  read_file: DocumentTextIcon,
  datadog_logs: DocumentTextIcon,
  datadog_metrics: ChartBarIcon,
  datadog_monitors: BellAlertIcon,
  datadog_events: CalendarIcon,
  datadog_apm: ClockIcon,
  pagerduty_incidents: BellAlertIcon,
  pagerduty_incident: BellAlertIcon,
  pagerduty_oncall: UserIcon,
}

const NOUNS: Record<string, [string, string]> = {
  ov: ['API call', 'API calls'],
  ov_sql: ['SQL query', 'SQL queries'],
  ov_export: ['export', 'exports'],
  ov_search: ['trackor search', 'trackor searches'],
  ov_map: ['map lookup', 'map lookups'],
  ov_case: ['case', 'cases'],
  source_search: ['code search', 'code searches'],
  source_read: ['source file', 'source files'],
  github_clone: ['repo', 'repos'],
  read_skill: ['skill', 'skills'],
  read_file: ['file', 'files'],
  datadog_logs: ['log search', 'log searches'],
  datadog_metrics: ['metric query', 'metric queries'],
  datadog_monitors: ['monitor check', 'monitor checks'],
  datadog_events: ['event search', 'event searches'],
  datadog_apm: ['APM query', 'APM queries'],
  pagerduty_incidents: ['incident search', 'incident searches'],
  pagerduty_incident: ['incident', 'incidents'],
  pagerduty_oncall: ['on-call check', 'on-call checks'],
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
    if (name === 'pagerduty_incident') return String(a.incident)
    if (name.startsWith('datadog_') || name.startsWith('pagerduty_'))
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
    if (name === 'source_search')
      return `${a.source}: /${a.pattern}/${a.path ? `  in ${a.path}` : ''}`
    if (name === 'source_read' || name === 'read_file')
      return `${a.source ? `${a.source}/` : ''}${a.path}`
    if (name === 'github_clone') return String(a.url)
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

function ToolRow({ tool }: { tool: ToolActivity }) {
  const [open, setOpen] = useState(false)
  const Icon = ICONS[tool.name] ?? CommandLineIcon
  const input = readableInput(tool)

  return (
    <div>
      <button
        type="button"
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
        <div className="mt-1 mb-2 ml-7 space-y-2">
          {input ? <Block title="Input" text={input} /> : null}
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
        <div className="border-line mt-1 ml-1.5 border-l-2 pl-2">
          {tools.map((t) => (
            <ToolRow key={t.id} tool={t} />
          ))}
        </div>
      ) : null}
    </div>
  )
}
