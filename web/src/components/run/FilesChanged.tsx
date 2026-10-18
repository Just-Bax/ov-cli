import {
  CaretRight as ChevronRightIcon,
  FilePlus as DocumentPlusIcon,
  NotePencil as PencilSquareIcon,
} from '@phosphor-icons/react'
import { memo, useEffect, useState } from 'react'
import type { FileEdit, RunDetails } from '@shared/types.ts'
import { useSkeleton } from '@/components/common/skeletons'
import { reportError } from '@/components/common/Toasts'
import { Skeleton } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { prefetch, take } from '@/lib/prefetch'
import { Diff } from './Diff'

type FileSummary = {
  path: string
  created: boolean
  added: number
  removed: number
  edits: FileEdit[]
}

function summarize(edits: FileEdit[]): FileSummary[] {
  const byPath = new Map<string, FileSummary>()
  for (const e of edits) {
    const entry = byPath.get(e.path) ?? {
      path: e.path,
      created: false,
      added: 0,
      removed: 0,
      edits: [],
    }
    entry.created ||= e.created
    entry.added += e.added
    entry.removed += e.removed
    entry.edits.push(e)
    byPath.set(e.path, entry)
  }

  return [...byPath.values()]
}

function LineCounts({ added, removed }: { added: number; removed: number }) {
  return (
    <span className="shrink-0 font-mono text-[11.5px] tabular-nums">
      <span className="text-ok">+{added}</span> <span className="text-danger">-{removed}</span>
    </span>
  )
}

function splitPath(path: string): [string, string] {
  const at = path.lastIndexOf('/')
  return at < 0 ? ['', path] : [path.slice(0, at + 1), path.slice(at + 1)]
}

const DETAIL_SLOT = 'edit'

function FileRow({ runId, file }: { runId: string; file: FileSummary }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<RunDetails['edits']>()
  const [folder, name] = splitPath(file.path)
  const Icon = file.created ? DocumentPlusIcon : PencilSquareIcon
  const lazyIds = file.edits.filter((e) => e.lazy && e.before === undefined).map((e) => e.id)
  const lazy = lazyIds.length > 0
  const key = `${runId}:${lazyIds.join(',')}`
  const loading = useSkeleton(open && lazy && !detail)

  useEffect(() => {
    if (!open || !lazy || detail) return

    let stale = false
    take(DETAIL_SLOT, key, () => api.runDetails(runId, [], lazyIds))
      .then((d) => !stale && setDetail(d.edits))
      .catch(reportError)

    return () => {
      stale = true
    }
  }, [open, lazy, detail, key, runId])

  return (
    <div>
      <button
        type="button"
        onMouseEnter={() => {
          if (lazy && !detail) prefetch(DETAIL_SLOT, key, () => api.runDetails(runId, [], lazyIds))
        }}
        onClick={() => setOpen((v) => !v)}
        className="hover:bg-raised flex w-full items-center gap-2.5 rounded-full px-3 py-1.5 text-left"
      >
        <ChevronRightIcon
          className={cn('text-faint size-3 shrink-0 transition-transform', open && 'rotate-90')}
        />
        <Icon className={cn('size-3.5 shrink-0', file.created ? 'text-ok' : 'text-brand')} />
        <span className="min-w-0 flex-1 truncate text-[12.5px]" title={file.path}>
          <span className="text-faint">{folder}</span>
          <span className="text-fg font-medium">{name}</span>
        </span>
        {file.created ? (
          <span className="bg-ok-soft text-ok shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium">
            new
          </span>
        ) : null}
        <LineCounts added={file.added} removed={file.removed} />
      </button>
      {open && lazy && !detail && loading ? (
        <div className="mt-1 mb-2 px-1">
          <Skeleton className="h-24 w-full rounded-2xl" />
        </div>
      ) : null}
      {open && (!lazy || detail) ? (
        <div className="mt-1 mb-2 space-y-2 px-1">
          {file.edits.map((e) => (
            <div key={e.id} className="border-line overflow-hidden rounded-2xl border">
              <Diff
                before={e.before ?? detail?.[e.id]?.before ?? ''}
                after={e.after ?? detail?.[e.id]?.after ?? ''}
              />
              {e.truncated ? (
                <div className="text-faint border-line border-t px-3 py-1.5 text-[11px]">
                  Long file: only the first part is shown.
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function sameEdits(
  a: { runId: string; edits: FileEdit[] },
  b: { runId: string; edits: FileEdit[] },
): boolean {
  return (
    a.runId === b.runId &&
    a.edits.length === b.edits.length &&
    a.edits.every((e, i) => e === b.edits[i])
  )
}

export const FilesChanged = memo(function FilesChanged({
  runId,
  edits,
}: {
  runId: string
  edits: FileEdit[]
}) {
  const [open, setOpen] = useState(false)
  const files = summarize(edits)
  if (!files.length) return null

  const added = files.reduce((n, f) => n + f.added, 0)
  const removed = files.reduce((n, f) => n + f.removed, 0)

  return (
    <div className="border-line-strong/70 rounded-2xl border p-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="hover:bg-raised flex w-full items-center gap-2.5 rounded-xl px-3 py-1.5 text-left"
      >
        <ChevronRightIcon
          className={cn('text-faint size-3 shrink-0 transition-transform', open && 'rotate-90')}
        />
        <span className="text-fg flex-1 text-[12.5px] font-semibold">
          {files.length} file{files.length === 1 ? '' : 's'} changed
        </span>
        <LineCounts added={added} removed={removed} />
      </button>
      {open ? (
        <div className="px-1 pb-1">
          {files.map((f) => (
            <FileRow key={f.path} runId={runId} file={f} />
          ))}
        </div>
      ) : null}
    </div>
  )
}, sameEdits)
