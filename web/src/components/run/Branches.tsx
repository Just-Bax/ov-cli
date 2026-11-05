import { ArrowsSplit, type IconProps } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { RunSummary, ThreadLink } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { go, href } from '@/lib/route'
import { allRuns, refreshRuns, useRuns } from '@/lib/runs'
import { plural } from '@/lib/text'

export function BranchIcon({ className, ...props }: IconProps) {
  return <ArrowsSplit className={cn('rotate-90', className)} {...props} />
}

export async function openThread(made: Promise<{ id: string }>): Promise<void> {
  const { id } = await made
  await refreshRuns()
  go({ page: 'thread', id })
}

export function LineageNote({ label, thread }: { label: string; thread?: ThreadLink | null }) {
  return (
    <div className="text-muted flex items-center gap-3 text-[12px]">
      <div className="bg-line h-px flex-1" />
      <span className="inline-flex min-w-0 items-center gap-1.5">
        <BranchIcon className="size-3.5 shrink-0" />
        <span className="shrink-0">{label}</span>
        {thread ? (
          <a
            href={href({ page: 'thread', id: thread.id })}
            className="text-brand-strong truncate font-medium hover:underline"
          >
            {thread.title}
          </a>
        ) : (
          <span>a deleted thread</span>
        )}
      </span>
      <div className="bg-line h-px flex-1" />
    </div>
  )
}

export function InheritedToggle({
  turns,
  open,
  onToggle,
}: {
  turns: number
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex justify-center">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="text-muted hover:text-fg hover:bg-raised rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
      >
        {open
          ? 'Hide the turns this branch came with'
          : `Show the ${plural(turns, 'turn')} this branch came with`}
      </button>
    </div>
  )
}

function branchVersion(runs: RunSummary[], parentId: string): string {
  return runs
    .filter((r) => r.parentId === parentId)
    .map((r) => `${r.id}:${r.title}`)
    .join(',')
}

export function useBranches(runId: string): RunSummary[] {
  const list = useRuns()
  const version = branchVersion(allRuns(list), runId)
  const [branches, setBranches] = useState<RunSummary[]>([])

  useEffect(() => {
    let live = true
    api
      .branches(runId)
      .then((found) => live && setBranches(found.branches))
      .catch(reportError)
    return () => {
      live = false
    }
  }, [runId, version])

  return branches
}

export function BranchedIntoNotes({ branches }: { branches: RunSummary[] }) {
  return branches.map((branch) => (
    <LineageNote key={branch.id} label="Branched into" thread={branch} />
  ))
}
