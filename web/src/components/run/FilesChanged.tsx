import { ChevronRightIcon, DocumentPlusIcon, PencilSquareIcon } from '@heroicons/react/24/outline'
import { useState } from 'react'
import type { FileEdit } from '@shared/types.ts'
import { cn } from '@/lib/cn'
import { Diff } from './Diff'

type FileSummary = {
  path: string
  created: boolean
  added: number
  removed: number
  edits: FileEdit[]
}

export function summarize(edits: FileEdit[]): FileSummary[] {
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

export function LineCounts({ added, removed }: { added: number; removed: number }) {
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

function FileRow({ file }: { file: FileSummary }) {
  const [open, setOpen] = useState(false)
  const [folder, name] = splitPath(file.path)
  const Icon = file.created ? DocumentPlusIcon : PencilSquareIcon

  return (
    <div>
      <button
        type="button"
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
      {open ? (
        <div className="mt-1 mb-2 space-y-2 px-1">
          {file.edits.map((e) => (
            <div key={e.id} className="border-line overflow-hidden rounded-2xl border">
              <Diff before={e.before} after={e.after} />
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

export function FilesChanged({ edits }: { edits: FileEdit[] }) {
  const files = summarize(edits)
  if (!files.length) return null

  const added = files.reduce((n, f) => n + f.added, 0)
  const removed = files.reduce((n, f) => n + f.removed, 0)

  return (
    <div className="border-line-strong/70 rounded-2xl border p-2">
      <div className="flex items-center gap-2 px-3 pt-1 pb-1.5">
        <span className="text-fg text-[12.5px] font-semibold">
          {files.length} file{files.length === 1 ? '' : 's'} changed
        </span>
        <LineCounts added={added} removed={removed} />
      </div>
      {files.map((f) => (
        <FileRow key={f.path} file={f} />
      ))}
    </div>
  )
}
