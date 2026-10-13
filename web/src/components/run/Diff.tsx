import { diffLines, diffWordsWithSpace } from 'diff'
import { CaretUpDown as ChevronUpDownIcon } from '@phosphor-icons/react'
import { type ReactNode, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'

type Line = {
  type: 'add' | 'del' | 'same'
  text: string
  oldNo?: number
  newNo?: number
  parts?: ReactNode
}
type Row = Line | { type: 'gap'; rows: Line[] }

const CONTEXT = 3
const MIN_HIDDEN_LINES = 3
const REWRITTEN_RATIO = 0.6

function dedent(before: string, after: string): [string, string] {
  const lines = `${before}\n${after}`.split('\n').filter((l) => l.trim())
  const indent = Math.min(...lines.map((l) => /^[ \t]*/.exec(l)![0].replace(/\t/g, '    ').length))
  if (!Number.isFinite(indent) || indent === 0) return [before, after]

  const strip = (s: string) =>
    s
      .split('\n')
      .map((l) =>
        l
          .replace(/\t/g, '    ')
          .slice(Math.min(indent, /^ */.exec(l.replace(/\t/g, '    '))![0].length)),
      )
      .join('\n')

  return [strip(before), strip(after)]
}

function markWords(oldText: string, newText: string): [ReactNode, ReactNode] {
  const parts = diffWordsWithSpace(oldText, newText)
  const changed = parts.filter((p) => p.added || p.removed).reduce((n, p) => n + p.value.length, 0)
  const mostlyRewritten = changed > Math.max(oldText.length, newText.length) * REWRITTEN_RATIO
  if (mostlyRewritten) return [oldText, newText]

  const oldNodes: ReactNode[] = []
  const newNodes: ReactNode[] = []
  parts.forEach((p, i) => {
    if (p.removed)
      oldNodes.push(
        <mark key={i} className="rounded-sm bg-[#f9c0c0] text-inherit">
          {p.value}
        </mark>,
      )
    else if (p.added)
      newNodes.push(
        <mark key={i} className="rounded-sm bg-[#aef0bf] text-inherit">
          {p.value}
        </mark>,
      )
    else {
      oldNodes.push(p.value)
      newNodes.push(p.value)
    }
  })

  return [oldNodes, newNodes]
}

function markReplacedLines(lines: Line[]): void {
  for (let i = 0; i < lines.length;) {
    if (lines[i].type !== 'del') {
      i++
      continue
    }

    let d = i
    while (d < lines.length && lines[d].type === 'del') d++
    let a = d
    while (a < lines.length && lines[a].type === 'add') a++
    const pairs = Math.min(d - i, a - d)
    for (let k = 0; k < pairs; k++) {
      const [o, n] = markWords(lines[i + k].text, lines[d + k].text)
      lines[i + k].parts = o
      lines[d + k].parts = n
    }
    i = a
  }
}

function buildRows(rawBefore: string, rawAfter: string): Row[] {
  const [before, after] = dedent(rawBefore.replace(/\r\n/g, '\n'), rawAfter.replace(/\r\n/g, '\n'))

  const lines: Line[] = []
  let oldNo = 1
  let newNo = 1
  for (const part of diffLines(before, after)) {
    for (const text of part.value.replace(/\n$/, '').split('\n')) {
      if (part.added) lines.push({ type: 'add', text, newNo: newNo++ })
      else if (part.removed) lines.push({ type: 'del', text, oldNo: oldNo++ })
      else lines.push({ type: 'same', text, oldNo: oldNo++, newNo: newNo++ })
    }
  }

  markReplacedLines(lines)

  const rows: Row[] = []
  for (let i = 0; i < lines.length;) {
    if (lines[i].type !== 'same') {
      rows.push(lines[i++])
      continue
    }

    let j = i
    while (j < lines.length && lines[j].type === 'same') j++
    const run = lines.slice(i, j)
    const head = i === 0 ? 0 : CONTEXT
    const tail = j === lines.length ? 0 : CONTEXT
    if (run.length - head - tail >= MIN_HIDDEN_LINES) {
      rows.push(
        ...run.slice(0, head),
        { type: 'gap', rows: run.slice(head, run.length - tail) },
        ...run.slice(run.length - tail),
      )
    } else {
      rows.push(...run)
    }
    i = j
  }

  return rows
}

const ROW_BG = { add: 'bg-[#eafbee]', del: 'bg-[#fdeeee]', same: '' }
const GUTTER_BG = { add: 'bg-[#d8f5e0]', del: 'bg-[#fbdcdc]', same: 'bg-[#f7f9fa]' }
const SIGN = { add: '+', del: '-', same: '' }

export function Diff({ before, after }: { before: string; after: string }) {
  const initial = useMemo(() => buildRows(before, after), [before, after])
  const [rows, setRows] = useState(initial)
  const lines = initial.flatMap((r) => (r.type === 'gap' ? [] : [r]))
  const added = lines.filter((r) => r.type === 'add').length
  const removed = lines.filter((r) => r.type === 'del').length

  return (
    <div>
      <div className="text-muted border-line flex items-center gap-2.5 border-b px-4 py-1.5 text-[11.5px]">
        <span className="text-ok font-semibold">+{added}</span>
        <span className="text-danger font-semibold">-{removed}</span>
        {!before ? <span>new</span> : null}
      </div>
      <div className="max-h-[520px] scrollbar-thin overflow-auto font-mono text-[12.5px] leading-[20px]">
        <table className="min-w-full border-collapse">
          <tbody>
            {rows.map((row, i) =>
              row.type === 'gap' ? (
                <tr key={`g${i}`}>
                  <td colSpan={3} className="p-0">
                    <button
                      type="button"
                      onClick={() =>
                        setRows([...rows.slice(0, i), ...row.rows, ...rows.slice(i + 1)])
                      }
                      className="text-brand-strong hover:bg-brand-soft sticky left-0 flex w-full items-center gap-2 bg-[#f3f8fd] px-3 py-1 text-left font-sans text-[11.5px]"
                    >
                      <ChevronUpDownIcon className="size-3" /> Show {row.rows.length} unchanged
                      lines
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={i} className={ROW_BG[row.type]}>
                  <td
                    className={cn(
                      'text-faint sticky left-0 w-[1%] px-2 text-right whitespace-nowrap select-none',
                      GUTTER_BG[row.type],
                    )}
                  >
                    <span className="inline-block w-7">{row.type === 'add' ? '' : row.oldNo}</span>
                    <span className="inline-block w-7">{row.type === 'del' ? '' : row.newNo}</span>
                  </td>
                  <td
                    className={cn(
                      'w-[1%] pl-2 select-none',
                      row.type === 'add' ? 'text-ok' : row.type === 'del' ? 'text-danger' : '',
                    )}
                  >
                    {SIGN[row.type]}
                  </td>
                  <td className="text-fg pr-6 pl-1 whitespace-pre">
                    {row.parts ?? (row.text || ' ')}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
