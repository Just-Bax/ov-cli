import {
  ArrowClockwise as RerunIcon,
  ArrowCounterClockwise as RevertIcon,
  CaretDown as CaretDownIcon,
  CaretUp as CaretUpIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
} from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import type { CellChange, DataChange, Grid, GridColumn, GridRow } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button, Chip, type Tone } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useApply } from '@/lib/optimistic'
import { timeWithDay } from '@/lib/time'

const DAY: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
const PLACEHOLDER = /\{([A-Za-z0-9_.]+)\}/g
const RESULT_KEY = '_status'
const ERROR_KEY = '_error'
const FAILED = 'failed'
const UNCHANGED = 'unchanged'
const SETTLED_CHANGE = new Set<DataChange['state']>(['done', 'stopped'])
const TRACKOR_FORM_PATH = '/form/ConfigAppForm.do?id='
const EMPTY_VALUE = '(empty)'
const PERCENT = 100

const STATUS_TONES: [RegExp, Tone][] = [
  [/without (errors|warnings)/i, 'ok'],
  [/fail|error|reject|cancel|invalid|interrupt|not run/i, 'danger'],
  [/warn|pending|queue|wait|hold|stopp/i, 'warn'],
  [/running|progress|importing/i, 'brand'],
  [/success|done|complete|updated|executed|active|enabled|^ok$/i, 'ok'],
]

type Sort = { key: string; descending: boolean }

function textOf(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isChange(value: unknown): value is CellChange {
  return typeof value === 'object' && value !== null && 'after' in value
}

function cellText(column: GridColumn, row: GridRow): string {
  const value = row[column.key]
  return isChange(value) ? `${textOf(value.before)} ${textOf(value.after)}` : textOf(value)
}

function statusTone(value: string): Tone {
  return STATUS_TONES.find(([pattern]) => pattern.test(value))?.[1] ?? 'neutral'
}

function resolved(href: string, row: GridRow, baseUrl?: string): string {
  const filled = href.replace(PLACEHOLDER, (_, key: string) => encodeURIComponent(textOf(row[key])))
  return filled.startsWith('/') && baseUrl ? `${baseUrl}${filled}` : filled
}

function compare(column: GridColumn, a: GridRow, b: GridRow): number {
  const left = a[column.key]
  const right = b[column.key]
  if (column.type === 'number') {
    const x = Number(left)
    const y = Number(right)
    if (Number.isNaN(x) || Number.isNaN(y)) return Number.isNaN(x) ? 1 : -1
    return x - y
  }

  const x = isChange(left) ? textOf(left.after) : textOf(left)
  const y = isChange(right) ? textOf(right.after) : textOf(right)
  return x.localeCompare(y, undefined, { numeric: true, sensitivity: 'base' })
}

function Link({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-brand-strong font-medium hover:underline"
    >
      {children}
    </a>
  )
}

function ChangeCell({ value }: { value: CellChange }) {
  const before = textOf(value.before)
  const after = textOf(value.after)
  if (before === after) return <span className="text-faint">{after || EMPTY_VALUE}</span>

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-faint line-through">{before || EMPTY_VALUE}</span>
      <span className="bg-ok-soft text-ok rounded-md px-1.5 py-px font-medium">
        {after || EMPTY_VALUE}
      </span>
    </span>
  )
}

function Cell({ column, row, baseUrl }: { column: GridColumn; row: GridRow; baseUrl?: string }) {
  const value = row[column.key]
  const text = textOf(value)

  switch (column.type) {
    case 'change':
      return isChange(value) ? <ChangeCell value={value} /> : null
    case 'number':
      return <span className="tabular-nums">{text}</span>
    case 'status':
      return text ? <Chip tone={statusTone(text)}>{text}</Chip> : null
    case 'trackor':
      return baseUrl && column.idKey && row[column.idKey] ? (
        <Link href={`${baseUrl}${TRACKOR_FORM_PATH}${textOf(row[column.idKey])}`}>{text}</Link>
      ) : (
        <>{text}</>
      )
    case 'link':
      return text && column.href ? (
        <Link href={resolved(column.href, row, baseUrl)}>{text}</Link>
      ) : (
        <>{text}</>
      )
    default:
      return <>{text}</>
  }
}

const CHANGE_LABELS: Record<DataChange['state'], (c: DataChange) => [string, Tone]> = {
  proposed: () => ['Waiting for approval', 'warn'],
  running: (c) => [`Writing ${c.done} of ${c.total}`, 'brand'],
  done: (c) => (c.failed ? [`Done, ${c.failed} failed`, 'warn'] : ['Done', 'ok']),
  stopped: (c) => [`Stopped after ${c.done} of ${c.total}`, 'warn'],
  rejected: () => ['Rejected, nothing written', 'neutral'],
  blocked: () => ['Read-only thread, nothing written', 'neutral'],
}

function ChangeHeader({ grid, change }: { grid: Grid; change: DataChange }) {
  const [label, tone] = CHANGE_LABELS[change.state](change)
  const already = change.unchanged ? `, ${change.unchanged} already set` : ''

  return (
    <>
      <div className="min-w-0 flex-1">
        <div className="text-fg text-[13.5px] leading-snug font-semibold">{grid.title}</div>
        <div className="text-muted mt-1 text-[12px]">
          {change.total} {change.trackorType} trackors on {grid.instance}:{' '}
          {change.fields.join(', ')}
          {already}
        </div>
      </div>
      <Chip tone={tone}>{label}</Chip>
    </>
  )
}

function GridHeader({ grid, runId }: { grid: Grid; runId: string }) {
  const apply = useApply()
  const shown = grid.rows.length
  const count = grid.total > shown ? `${shown} of ${grid.total} rows` : `${shown} rows`
  const meta = [count, grid.instance, timeWithDay(grid.ranAt, DAY)].filter(Boolean)

  const rerun = () => {
    apply({ type: 'grid', grid: { id: grid.id, loading: true, error: null } })
    api.rerunGrid(runId, grid.id).catch((e: unknown) => {
      apply({ type: 'grid', grid: { id: grid.id, loading: false } })
      reportError(e)
    })
  }

  return (
    <>
      <div className="min-w-0 flex-1">
        <div className="text-fg text-[13.5px] leading-snug font-semibold">{grid.title}</div>
        <div className="text-muted mt-1 text-[12px]">{meta.join(' / ')}</div>
      </div>
      {grid.source ? (
        <Button
          size="sm"
          variant="ghost"
          busy={grid.loading}
          disabled={grid.loading}
          onClick={rerun}
        >
          <RerunIcon className="size-3.5" /> {grid.loading ? 'Running' : 'Re-run'}
        </Button>
      ) : null}
    </>
  )
}

function RevertButton({ grid, runId }: { grid: Grid; runId: string }) {
  const [busy, setBusy] = useState(false)

  const revert = async () => {
    setBusy(true)
    try {
      await api.revertGrid(runId, grid.id)
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Button size="sm" variant="ghost" busy={busy} disabled={busy} onClick={() => void revert()}>
      <RevertIcon className="size-3.5" /> Revert {grid.change?.updated}
    </Button>
  )
}

function HeaderCell({
  column,
  sort,
  onSort,
}: {
  column: GridColumn
  sort?: Sort
  onSort: (key: string) => void
}) {
  const active = sort?.key === column.key
  const Caret = active && sort.descending ? CaretDownIcon : CaretUpIcon

  return (
    <th
      className={cn(
        'bg-raised border-line-strong text-muted sticky top-0 z-[1] border-b px-3 py-2 text-left font-semibold whitespace-nowrap',
        column.type === 'number' && 'text-right',
      )}
    >
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className="hover:text-fg inline-flex items-center gap-1"
      >
        {column.label}
        <Caret className={cn('size-3', active ? 'text-fg' : 'text-transparent')} />
      </button>
    </th>
  )
}

export function GridCard({
  grid,
  runId,
  inherited = false,
}: {
  grid: Grid
  runId: string
  inherited?: boolean
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>()
  const [failedOnly, setFailedOnly] = useState(false)
  const change = grid.change
  const settled = change ? SETTLED_CHANGE.has(change.state) : false

  const columns = useMemo<GridColumn[]>(
    () =>
      settled
        ? [...grid.columns, { key: RESULT_KEY, label: 'Result', type: 'status' }]
        : grid.columns,
    [grid.columns, settled],
  )

  const rows = useMemo(() => {
    const wanted = query.trim().toLowerCase()
    const filtered = grid.rows.filter(
      (row) =>
        (!failedOnly || row[RESULT_KEY] === FAILED) &&
        (!wanted || columns.some((c) => cellText(c, row).toLowerCase().includes(wanted))),
    )
    const column = columns.find((c) => c.key === sort?.key)
    if (!column || !sort) return filtered

    const sorted = [...filtered].sort((a, b) => compare(column, a, b))
    return sort.descending ? sorted.reverse() : sorted
  }, [grid.rows, columns, query, sort, failedOnly])

  const toggleSort = (key: string) =>
    setSort((s) =>
      s?.key === key
        ? s.descending
          ? undefined
          : { key, descending: true }
        : { key, descending: false },
    )

  return (
    <div className="border-line-strong/70 overflow-hidden rounded-2xl border">
      <div className="bg-raised flex items-start gap-3 px-4 py-3">
        {change ? (
          <ChangeHeader grid={grid} change={change} />
        ) : (
          <GridHeader grid={grid} runId={runId} />
        )}
      </div>
      {change?.state === 'running' ? (
        <div className="bg-line h-1">
          <div
            className="bg-brand h-full"
            style={{ width: `${(PERCENT * change.done) / Math.max(change.total, 1)}%` }}
          />
        </div>
      ) : null}
      {grid.error ? (
        <div className="border-line bg-danger-soft text-danger border-t px-4 py-2 text-[12px]">
          {grid.error}
        </div>
      ) : null}
      <div className="border-line flex items-center gap-2 border-t px-4 py-2">
        <label className="border-line-strong focus-within:border-brand flex h-8 w-56 items-center gap-2 rounded-full border bg-white px-3">
          <MagnifyingGlassIcon className="text-faint size-3.5" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter rows"
            className="placeholder:text-faint w-full bg-transparent text-[12.5px] outline-none"
          />
        </label>
        {change?.failed && settled ? (
          <Button
            size="sm"
            variant={failedOnly ? 'secondary' : 'ghost'}
            onClick={() => setFailedOnly((v) => !v)}
          >
            Failed only
          </Button>
        ) : null}
        <span className="text-faint ml-auto text-[12px]">
          {rows.length === grid.rows.length
            ? `${rows.length} rows`
            : `${rows.length} of ${grid.rows.length}`}
        </span>
        {change?.state === 'done' && change.updated && !inherited ? (
          <RevertButton grid={grid} runId={runId} />
        ) : null}
      </div>
      <div className="border-line scrollbar-shown max-h-[420px] overflow-auto overscroll-contain border-t">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr>
              {columns.map((c) => (
                <HeaderCell key={c.key} column={c} sort={sort} onSort={toggleSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={i}
                className={cn(
                  'even:bg-raised/60 border-line border-b last:border-b-0',
                  row[RESULT_KEY] === UNCHANGED && 'opacity-60',
                )}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      'text-text px-3 py-1.5 align-middle whitespace-nowrap',
                      c.type === 'number' && 'text-right',
                    )}
                  >
                    <div
                      title={c.type === 'change' ? undefined : cellText(c, row)}
                      className={cn(c.type !== 'change' && 'max-w-[360px] truncate')}
                    >
                      <Cell column={c} row={row} baseUrl={grid.baseUrl} />
                      {c.key === RESULT_KEY && row[ERROR_KEY] ? (
                        <span className="text-danger ml-2" title={textOf(row[ERROR_KEY])}>
                          {textOf(row[ERROR_KEY])}
                        </span>
                      ) : null}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length ? (
          <div className="text-muted px-4 py-6 text-center text-[12.5px]">
            {grid.rows.length ? 'No rows match.' : 'No rows.'}
          </div>
        ) : null}
      </div>
    </div>
  )
}
