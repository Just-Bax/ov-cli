import {
  Archive as ArchiveBoxArrowDownIcon,
  BellRinging as BellAlertIcon,
  BookOpen as BookOpenIcon,
  Calendar as CalendarIcon,
  ChartBar as ChartBarIcon,
  CaretRight as ChevronRightIcon,
  Clock as ClockIcon,
  Database as CircleStackIcon,
  CodeBlock as CodeBracketSquareIcon,
  TerminalWindow as CommandLineIcon,
  FilePlus as DocumentPlusIcon,
  FileText as DocumentTextIcon,
  Folder as FolderIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
  MapTrifold as MapIcon,
  NotePencil as PencilSquareIcon,
  Ticket as TicketIcon,
  User as UserIcon,
  Users as UsersIcon,
  ChatCircleDots as ChatBubbleLeftEllipsisIcon,
  Check as CheckIcon,
  CheckCircle as CheckCircleIcon,
  ArrowCircleUp as ArrowUpCircleIcon,
  ArrowsLeftRight as ArrowsRightLeftIcon,
  Moon as MoonIcon,
  X as XMarkIcon,
  Stop as StopIcon,
  ArrowSquareDownRight as BackgroundIcon,
  Browser as BrowserIcon,
  Eye as EyeIcon,
  Cursor as CursorIcon,
  HandGrabbing as HandIcon,
  Keyboard as KeyboardIcon,
  ListChecks as ListChecksIcon,
  ArrowsDownUp as ScrollIcon,
  AppWindow as DialogIcon,
  Tabs as TabsIcon,
} from '@phosphor-icons/react'
import { memo, type ReactNode, useEffect, useState } from 'react'
import type { CommandVerdict, ToolActivity } from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { reportError } from '@/components/common/Toasts'
import { CopyButton, type Icon, Shimmer, Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { prefetch, take } from '@/lib/prefetch'
import { seconds } from '@/lib/time'

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
  browser_open: BrowserIcon,
  browser_run: BrowserIcon,
  browser_snapshot: EyeIcon,
  browser_click: CursorIcon,
  browser_hover: CursorIcon,
  browser_mouse: CursorIcon,
  browser_drag: HandIcon,
  browser_type: KeyboardIcon,
  browser_select: ListChecksIcon,
  browser_press: KeyboardIcon,
  browser_scroll: ScrollIcon,
  browser_wait: ClockIcon,
  browser_dialog: DialogIcon,
  browser_tab: TabsIcon,
  browser_close: XMarkIcon,
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
  browser_open: ['page opened', 'pages opened'],
  browser_run: ['browser task', 'browser tasks'],
  browser_snapshot: ['look at the page', 'looks at the page'],
  browser_click: ['click', 'clicks'],
  browser_hover: ['hover', 'hovers'],
  browser_mouse: ['mouse press', 'mouse presses'],
  browser_drag: ['drag', 'drags'],
  browser_wait: ['wait', 'waits'],
  browser_type: ['text entry', 'text entries'],
  browser_select: ['choice', 'choices'],
  browser_press: ['key press', 'key presses'],
  browser_scroll: ['scroll', 'scrolls'],
  browser_dialog: ['dialog answered', 'dialogs answered'],
  browser_tab: ['tab change', 'tab changes'],
  browser_close: ['browser close', 'browser closes'],
}

export function summarize(tools: ToolActivity[]): string {
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
const TICK_MS = 1000

const VERDICT_TONE: Record<CommandVerdict['effect'], string> = {
  read: 'text-faint',
  change: 'text-warn',
  outside: 'text-danger',
  write: 'text-danger',
}

function useElapsed(startedAt: number | undefined, running: boolean): number | undefined {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!running || startedAt === undefined) return
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [running, startedAt])

  return running && startedAt !== undefined ? Math.max(0, now - startedAt) : undefined
}

function RowAction({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="text-faint hover:bg-raised hover:text-fg flex size-6 shrink-0 items-center justify-center rounded-full"
    >
      {children}
    </button>
  )
}

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
  const running = tool.status === 'running'
  const elapsed = useElapsed(tool.startedAt, running)

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
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onMouseEnter={() => {
            if (lazy && !detail)
              prefetch(DETAIL_SLOT, key, () => api.runDetails(runId, [tool.id], []))
          }}
          onClick={() => setOpen(!open)}
          className="hover:bg-raised flex min-w-0 flex-1 items-center gap-2 rounded-full px-2.5 py-1 text-left"
        >
          <ChevronRightIcon
            className={cn('text-faint size-3 shrink-0 transition-transform', open && 'rotate-90')}
          />
          {tool.status === 'error' ? (
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
            {tool.status === 'running' ? <Shimmer>{tool.label}</Shimmer> : tool.label}
          </span>
          {tool.verdict ? (
            <span
              title={tool.verdict.reason}
              className={cn(
                'max-w-56 shrink-0 truncate text-[11px] @max-[600px]:hidden',
                VERDICT_TONE[tool.verdict.effect],
              )}
            >
              {tool.verdict.effect}: {tool.verdict.reason}
            </span>
          ) : null}
          {tool.backgroundedAt !== undefined && running ? (
            <span className="bg-brand-soft text-brand-strong shrink-0 rounded-full px-1.5 text-[10.5px]">
              background
            </span>
          ) : null}
          {tool.stoppedAt !== undefined ? (
            <span className="text-faint shrink-0 text-[11px]">stopped</span>
          ) : null}
          {tool.ms !== undefined ? (
            <span className="text-faint shrink-0 text-[11px]">{seconds(tool.ms)}</span>
          ) : elapsed !== undefined ? (
            <span className="text-faint shrink-0 text-[11px] tabular-nums">{seconds(elapsed)}</span>
          ) : null}
        </button>
        {running && tool.backgroundedAt === undefined ? (
          <RowAction
            label="Move to background"
            onClick={() => void api.backgroundTool(runId, tool.id).catch(reportError)}
          >
            <BackgroundIcon className="size-3.5" />
          </RowAction>
        ) : null}
        {running && tool.stoppedAt === undefined ? (
          <RowAction
            label="Stop"
            onClick={() => void api.stopTool(runId, tool.id).catch(reportError)}
          >
            <StopIcon className="size-3.5" />
          </RowAction>
        ) : null}
      </div>
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
  const running = tools.find((t) => t.status === 'running' && t.backgroundedAt === undefined)
  const background = tools.filter(
    (t) => t.status === 'running' && t.backgroundedAt !== undefined,
  ).length
  const failed = tools.filter((t) => t.status === 'error').length
  const [open, setOpen] = useState(false)
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
        <span className="min-w-0 truncate text-[12.5px]">
          {running ? (
            <Shimmer>{running.label}</Shimmer>
          ) : (
            <span>
              {tools.length === 1 && tools[0].name === 'ov_case'
                ? tools[0].label
                : summarize(tools)}
            </span>
          )}
        </span>
        {background ? (
          <span className="text-brand-strong shrink-0 text-[11px]">{background} in background</span>
        ) : null}
        {failed ? <span className="text-danger shrink-0 text-[11px]">{failed} failed</span> : null}
        {!running && total ? (
          <span className="text-faint shrink-0 text-[11px]">{seconds(total)}</span>
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
