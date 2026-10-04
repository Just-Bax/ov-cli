import { ArrowUpRight, Network } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { CodeHint, GraphNode, GraphNodeType } from '@shared/types.ts'
import { TypeDot, TYPES } from '@/components/map/meta'
import { Button } from '@/components/ui'
import { findRefs, type Ref, type RefIndex, REF_KINDS } from '@/lib/references'
import { monaco } from '@/lib/monaco'

const MAX_LINKS = 6000
const CARD_WIDTH = 320

// Per-type colors for the pill behind a reference and its text, generated once from TYPES.
let stylesAdded = false
function addStyles() {
  if (stylesAdded) return
  stylesAdded = true
  const css = (Object.keys(TYPES) as GraphNodeType[])
    .map((type) => {
      const color = TYPES[type].color
      return [
        `.monaco-editor .ov-ref-${type} { background: ${color}1f; outline-color: ${color}1f; }`,
        `.monaco-editor .ov-ref-${type}.ov-ref-on { background: ${color}38; outline-color: ${color}38; }`,
        `.monaco-editor .ov-ref-text-${type} { color: ${color} !important; }`,
      ].join('\n')
    })
    .join('\n')
  const style = document.createElement('style')
  style.textContent = css
  document.head.appendChild(style)
}

function severity(level: CodeHint['severity']) {
  if (level === 'error') return monaco.MarkerSeverity.Error
  if (level === 'warn') return monaco.MarkerSeverity.Warning
  return monaco.MarkerSeverity.Info
}

type Hover = { ref: Ref; line: number; top: number; left: number }

export function CodeView({
  code,
  hints,
  refs,
  facts,
  onOpen,
  onShowOnMap,
  revealLine,
}: {
  code: string
  hints: CodeHint[]
  refs: RefIndex
  facts: (node: GraphNode) => string[]
  onOpen: (node: GraphNode) => void
  onShowOnMap: (node: GraphNode) => void
  revealLine?: { line: number; at: number }
}) {
  const frame = useRef<HTMLDivElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor>(undefined)
  const linksRef = useRef<monaco.editor.IEditorDecorationsCollection>(undefined)
  const activeRef = useRef<monaco.editor.IEditorDecorationsCollection>(undefined)
  const byLine = useRef(new Map<number, Ref[]>())
  const openRef = useRef(onOpen)
  openRef.current = onOpen
  const [hover, setHover] = useState<Hover>()
  const hideTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const keep = () => clearTimeout(hideTimer.current)
  const hideSoon = () => {
    clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => setHover(undefined), 180)
  }

  useEffect(() => {
    addStyles()
    const editor = monaco.editor.create(host.current!, {
      readOnly: true,
      theme: 'ov-light',
      language: 'sql',
      automaticLayout: true,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      fontSize: 12.5,
      lineHeight: 22,
      minimap: { enabled: true, renderCharacters: false, scale: 1 },
      scrollBeyondLastLine: false,
      smoothScrolling: true,
      padding: { top: 12, bottom: 12 },
      stickyScroll: { enabled: true },
      renderLineHighlight: 'line',
      occurrencesHighlight: 'singleFile',
      folding: true,
      guides: { indentation: true },
      scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
      fixedOverflowWidgets: true,
    })
    editorRef.current = editor
    linksRef.current = editor.createDecorationsCollection()
    activeRef.current = editor.createDecorationsCollection()

    const refAt = (position: monaco.Position | null) =>
      position
        ? byLine.current
            .get(position.lineNumber)
            ?.find((r) => r.start < position.column && position.column <= r.end + 1)
        : undefined

    const move = editor.onMouseMove((e) => {
      const position = e.target.position
      const onText = e.target.type === monaco.editor.MouseTargetType.CONTENT_TEXT
      const ref = onText ? refAt(position) : undefined
      if (!ref || !position) {
        hideSoon()
        return
      }
      keep()
      setHover((current) => {
        if (current?.ref === ref) return current
        const at = editor.getScrolledVisiblePosition({
          lineNumber: position.lineNumber,
          column: ref.start + 1,
        })
        if (!at) return current
        return { ref, line: position.lineNumber, top: at.top + at.height + 6, left: at.left }
      })
    })
    const leave = editor.onMouseLeave(hideSoon)
    const scroll = editor.onDidScrollChange(() => setHover(undefined))
    // A plain click on a reference opens it, as long as the user is not selecting text.
    const click = editor.onMouseUp((e) => {
      if (!editor.getSelection()?.isEmpty()) return
      const ref = refAt(e.target.position)
      if (ref) openRef.current(ref.node)
    })
    return () => {
      for (const d of [move, leave, scroll, click]) d.dispose()
      editor.getModel()?.dispose()
      editor.dispose()
    }
  }, [])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    const previous = editor.getModel()
    const model = monaco.editor.createModel(code.replace(/\r\n/g, '\n'), 'sql')
    editor.setModel(model)
    previous?.dispose()
    setHover(undefined)

    byLine.current = new Map()
    const decorations: monaco.editor.IModelDeltaDecoration[] = []
    for (let line = 1; line <= model.getLineCount() && decorations.length < MAX_LINKS; line++) {
      const found = findRefs(model.getLineContent(line), refs)
      if (!found.length) continue
      byLine.current.set(line, found)
      for (const r of found)
        decorations.push({
          range: new monaco.Range(line, r.start + 1, line, r.end + 1),
          options: {
            className: `ov-ref ov-ref-${r.node.type}`,
            inlineClassName: `ov-ref-text ov-ref-text-${r.node.type}`,
            stickiness: monaco.editor.TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
          },
        })
    }
    linksRef.current?.set(decorations)

    monaco.editor.setModelMarkers(
      model,
      'ov-hints',
      hints.map((h) => {
        const line = Math.min(Math.max(h.line, 1), model.getLineCount())
        return {
          severity: severity(h.severity),
          message: `${h.title}\n${h.detail}`,
          startLineNumber: line,
          endLineNumber: line,
          startColumn: model.getLineFirstNonWhitespaceColumn(line) || 1,
          endColumn: model.getLineMaxColumn(line),
        }
      }),
    )
    editor.setScrollTop(0)
  }, [code, hints, refs])

  useEffect(() => {
    activeRef.current?.set(
      hover
        ? [
            {
              range: new monaco.Range(
                hover.line,
                hover.ref.start + 1,
                hover.line,
                hover.ref.end + 1,
              ),
              options: { className: `ov-ref ov-ref-${hover.ref.node.type} ov-ref-on` },
            },
          ]
        : [],
    )
  }, [hover])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || !revealLine) return
    editor.revealLineInCenter(revealLine.line)
    editor.setSelection(new monaco.Range(revealLine.line, 1, revealLine.line, 1))
    editor.focus()
  }, [revealLine])

  const width = frame.current?.clientWidth ?? 0
  return (
    <div ref={frame} className="relative h-full w-full">
      <div ref={host} className="h-full w-full" />
      {hover ? (
        <RefCard
          hover={hover}
          facts={facts(hover.ref.node)}
          style={{
            top: hover.top,
            left: Math.max(8, Math.min(hover.left - 12, width - CARD_WIDTH - 24)),
            width: CARD_WIDTH,
          }}
          onEnter={keep}
          onLeave={hideSoon}
          onOpen={() => {
            setHover(undefined)
            onOpen(hover.ref.node)
          }}
          onShowOnMap={() => onShowOnMap(hover.ref.node)}
        />
      ) : null}
    </div>
  )
}

function RefCard({
  hover,
  facts,
  style,
  onEnter,
  onLeave,
  onOpen,
  onShowOnMap,
}: {
  hover: Hover
  facts: string[]
  style: React.CSSProperties
  onEnter: () => void
  onLeave: () => void
  onOpen: () => void
  onShowOnMap: () => void
}) {
  const { node, kind, text } = hover.ref
  const meta = TYPES[node.type]
  return (
    <div
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={style}
      className="border-line absolute z-50 rounded-2xl border bg-white p-3.5 shadow-[0_8px_28px_rgba(38,50,56,0.14)]"
    >
      <div className="flex items-start gap-2.5">
        <TypeDot type={node.type} />
        <div className="min-w-0 flex-1">
          <div className="text-fg text-[13px] leading-snug font-semibold break-words">
            {node.name}
          </div>
          <div className="text-muted mt-0.5 text-[11.5px]">
            {meta.label} - id {node.ref}
          </div>
        </div>
      </div>
      <div
        className="mt-3 flex items-center gap-2 rounded-full py-1 pr-3 pl-1"
        style={{ background: `${meta.color}12` }}
      >
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium text-white"
          style={{ background: meta.color }}
        >
          {REF_KINDS[kind]}
        </span>
        <code className="text-text min-w-0 truncate font-mono text-[11.5px]">{text}</code>
      </div>
      {facts.length ? (
        <div className="text-muted mt-2.5 space-y-1 px-1 text-[12px] leading-relaxed">
          {facts.map((f) => (
            <div key={f}>{f}</div>
          ))}
        </div>
      ) : null}
      <div className="mt-3 flex gap-2">
        <Button size="sm" variant="primary" onClick={onOpen}>
          <ArrowUpRight className="size-3.5" /> Open
        </Button>
        <Button size="sm" variant="secondary" onClick={onShowOnMap}>
          <Network className="size-3.5" /> Show on map
        </Button>
      </div>
    </div>
  )
}
