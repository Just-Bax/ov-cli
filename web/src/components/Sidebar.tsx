import { CircleAlert, CircleCheck, CircleSlash, Plus, Settings, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { RunStatus, RunSummary } from '@shared/types.ts'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { dialog } from '@/components/Dialog'
import { EditableTitle } from '@/components/EditableTitle'
import { Skeleton, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href, type Route } from '@/lib/route'

const RECENT_LIMIT = 40

export function StatusIcon({
  status,
  className,
  detailed,
}: {
  status: RunStatus
  className?: string
  detailed?: boolean
}) {
  if (status === 'running' || status === 'queued')
    return <Spinner className={cn('text-brand size-3', className)} />
  if (detailed && status === 'done')
    return <CircleCheck className={cn('text-ok size-3.5', className)} />
  if (detailed && status === 'cancelled')
    return <CircleSlash className={cn('text-faint size-3.5', className)} />
  if (detailed && status === 'error')
    return <CircleAlert className={cn('text-danger size-3.5', className)} />
  const dot: Record<string, string> = {
    waiting: 'bg-warn',
    error: 'bg-danger',
    cancelled: 'bg-line-strong',
    done: 'bg-ok',
  }
  return <span className={cn('block size-1.5 rounded-full', dot[status], className)} />
}

function dayLabel(ts: number): string {
  const day = new Date(ts).setHours(0, 0, 0, 0)
  const today = new Date().setHours(0, 0, 0, 0)
  if (day === today) return 'Today'
  if (day === today - 86_400_000) return 'Yesterday'
  const sameYear = new Date(ts).getFullYear() === new Date().getFullYear()
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}

function group(runs: RunSummary[]): [string, RunSummary[]][] {
  const groups = new Map<string, RunSummary[]>()
  for (const r of runs) {
    const label = ['queued', 'running', 'waiting'].includes(r.status)
      ? 'In progress'
      : dayLabel(r.createdAt)
    groups.set(label, [...(groups.get(label) ?? []), r])
  }
  const active = groups.get('In progress')
  groups.delete('In progress')
  return active ? [['In progress', active], ...groups] : [...groups]
}

function useRuns(): [RunSummary[] | undefined, () => void] {
  const [runs, setRuns] = useState<RunSummary[]>()
  const load = useCallback(() => {
    api
      .runs()
      .then(setRuns)
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    load()
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [load])
  return [runs, load]
}

function Avatar({ user }: { user?: string }) {
  const [broken, setBroken] = useState(false)
  if (!user || broken)
    return (
      <span className="bg-brand-soft text-brand-strong flex size-8 items-center justify-center rounded-full text-[13px] font-semibold">
        {(user ?? '?').slice(0, 1).toUpperCase()}
      </span>
    )
  return (
    <img
      src={`https://github.com/${encodeURIComponent(user)}.png?size=64`}
      alt=""
      onError={() => setBroken(true)}
      className="bg-raised size-8 rounded-full object-cover"
    />
  )
}

function RunItem({
  run,
  active,
  onChanged,
}: {
  run: RunSummary
  active: boolean
  onChanged: () => void
}) {
  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const ok = await dialog.confirm({
      title: 'Delete this run?',
      body: 'The conversation, findings and proposed changes are removed. This cannot be undone.',
      confirmLabel: 'Delete',
      tone: 'danger',
    })
    if (!ok) return
    await api.deleteRun(run.id)
    onChanged()
    if (active) go({ page: 'home' })
  }

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => go({ page: 'run', id: run.id })}
      onKeyDown={(e) => e.key === 'Enter' && go({ page: 'run', id: run.id })}
      className={cn(
        'group/run flex h-9 cursor-pointer items-center gap-2.5 rounded-full pr-1 pl-3.5 text-[12.5px] font-medium transition-colors outline-none',
        active
          ? 'bg-brand-soft text-brand-strong'
          : 'text-text hover:bg-canvas hover:text-brand-strong focus-visible:bg-canvas',
      )}
    >
      <span className="flex size-3 shrink-0 items-center justify-center">
        <StatusIcon status={run.status} />
      </span>
      <EditableTitle
        value={run.title}
        onSave={async (title) => {
          await api.renameRun(run.id, title)
          onChanged()
        }}
        className="min-w-0 flex-1 truncate"
        inputClassName="h-7 text-[12.5px] font-medium"
      />
      <button
        type="button"
        aria-label="Delete run"
        onClick={(e) => void remove(e)}
        className="text-faint hover:text-danger flex size-7 shrink-0 items-center justify-center rounded-full opacity-0 transition-opacity group-hover/run:opacity-100 hover:bg-black/[0.06] focus-visible:opacity-100"
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  )
}

export function Sidebar({ route, user }: { route: Route; user?: string }) {
  const [runs, reload] = useRuns()
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? (runs ?? []) : (runs ?? []).slice(0, RECENT_LIMIT)
  const onSettings = route.page === 'settings'

  return (
    <aside className="border-line-strong/60 flex w-[272px] shrink-0 flex-col border-r bg-white">
      <div className="flex h-16 shrink-0 items-center px-5">
        <a href="#/" aria-label="OV Agent home">
          <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto" />
        </a>
      </div>
      <div className="px-3 pb-2">
        <a
          href="#/"
          className="bg-brand hover:bg-brand-strong flex h-10 items-center justify-center gap-2 rounded-full text-[13px] font-medium text-white transition-colors"
        >
          <Plus className="size-4" strokeWidth={2.25} /> New run
        </a>
      </div>

      <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto px-3 pt-2 pb-4">
        {!runs ? (
          <div className="space-y-4 px-3 pt-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className={i % 2 ? 'h-3 w-3/5' : 'h-3 w-4/5'} />
            ))}
          </div>
        ) : null}
        {group(shown).map(([label, list], index) => (
          <div key={label} className={index ? 'mt-5' : 'mt-1'}>
            <div className="text-faint mb-1 px-3.5 text-[12px] font-medium">{label}</div>
            <div className="space-y-0.5">
              {list.map((r) => (
                <RunItem
                  key={r.id}
                  run={r}
                  active={route.page === 'run' && route.id === r.id}
                  onChanged={reload}
                />
              ))}
            </div>
          </div>
        ))}
        {!showAll && (runs?.length ?? 0) > RECENT_LIMIT ? (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="text-brand-strong hover:bg-canvas mt-3 h-9 w-full rounded-full px-3.5 text-left text-[12.5px] font-medium"
          >
            Show all {runs?.length} runs
          </button>
        ) : null}
        {runs && !runs.length ? (
          <div className="text-faint px-3.5 py-3 text-[12.5px]">
            Your runs appear here. Start one with a case number or a question.
          </div>
        ) : null}
      </div>

      <div className="border-line-strong/60 flex h-16 shrink-0 items-center gap-1 border-t px-3">
        <a
          href={href({ page: 'settings' })}
          className={cn(
            'flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-full pr-3 pl-1.5 transition-colors',
            onSettings ? 'bg-brand-soft' : 'hover:bg-canvas',
          )}
        >
          <Avatar user={user} />
          <span className="min-w-0">
            <span className="text-fg block truncate text-[13px] font-medium">
              {user ?? 'Not signed in'}
            </span>
            <span className="text-faint block text-[11.5px]">GitHub Copilot</span>
          </span>
        </a>
        <a
          href={href({ page: 'settings' })}
          aria-label="Settings"
          className={cn(
            'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors',
            onSettings
              ? 'bg-brand-soft text-brand-strong'
              : 'text-muted hover:bg-canvas hover:text-fg',
          )}
        >
          <Settings className="size-[18px]" strokeWidth={1.75} />
        </a>
      </div>
    </aside>
  )
}
