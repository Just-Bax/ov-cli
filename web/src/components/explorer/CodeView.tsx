import { useEffect, useRef } from 'react'
import type { CodeHint, GraphNode } from '@shared/types.ts'
import { TYPES } from '@/components/map/meta'
import { monaco } from '@/lib/monaco'

const TOKEN = /\b\d{6,12}\b|\b[A-Za-z][A-Za-z0-9_$#]{2,}\b/g
const MAX_LINKS = 4000

export type Resolve = (token: string) => GraphNode | undefined

// Hover and click need the resolver of the editor they fire in; models are keyed by uri.
const resolvers = new Map<string, { resolve: Resolve; describe: (n: GraphNode) => string }>()
let hoverRegistered = false

function registerHover() {
  if (hoverRegistered) return
  hoverRegistered = true
  monaco.languages.registerHoverProvider('sql', {
    provideHover(model, position) {
      const entry = resolvers.get(model.uri.toString())
      const word = model.getWordAtPosition(position)
      if (!entry || !word) return null
      const node = entry.resolve(word.word)
      if (!node) return null
      return {
        range: new monaco.Range(
          position.lineNumber,
          word.startColumn,
          position.lineNumber,
          word.endColumn,
        ),
        contents: [{ value: entry.describe(node) }],
      }
    },
  })
}

function severity(level: CodeHint['severity']) {
  if (level === 'error') return monaco.MarkerSeverity.Error
  if (level === 'warn') return monaco.MarkerSeverity.Warning
  return monaco.MarkerSeverity.Info
}

export function CodeView({
  code,
  hints,
  resolve,
  describe,
  onOpen,
  revealLine,
}: {
  code: string
  hints: CodeHint[]
  resolve: Resolve
  describe: (node: GraphNode) => string
  onOpen: (node: GraphNode) => void
  revealLine?: { line: number; at: number }
}) {
  const host = useRef<HTMLDivElement>(null)
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor>(undefined)
  const linksRef = useRef<monaco.editor.IEditorDecorationsCollection>(undefined)
  const openRef = useRef(onOpen)
  openRef.current = onOpen

  useEffect(() => {
    registerHover()
    const editor = monaco.editor.create(host.current!, {
      readOnly: true,
      theme: 'ov-light',
      language: 'sql',
      automaticLayout: true,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      fontSize: 12.5,
      lineHeight: 20,
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

    // A plain click on a linked name opens it, as long as the user is not selecting text.
    const click = editor.onMouseUp((e) => {
      const position = e.target.position
      if (!position || !editor.getSelection()?.isEmpty()) return
      const model = editor.getModel()
      const entry = model && resolvers.get(model.uri.toString())
      const word = model?.getWordAtPosition(position)
      const node = entry && word ? entry.resolve(word.word) : undefined
      if (node) openRef.current(node)
    })
    return () => {
      click.dispose()
      const model = editor.getModel()
      if (model) resolvers.delete(model.uri.toString())
      model?.dispose()
      editor.dispose()
    }
  }, [])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    const previous = editor.getModel()
    if (previous) resolvers.delete(previous.uri.toString())
    const model = monaco.editor.createModel(code.replace(/\r\n/g, '\n'), 'sql')
    resolvers.set(model.uri.toString(), { resolve, describe })
    editor.setModel(model)
    previous?.dispose()

    const decorations: monaco.editor.IModelDeltaDecoration[] = []
    for (let line = 1; line <= model.getLineCount() && decorations.length < MAX_LINKS; line++) {
      const text = model.getLineContent(line)
      for (const match of text.matchAll(TOKEN)) {
        const node = resolve(match[0])
        if (!node) continue
        decorations.push({
          range: new monaco.Range(line, match.index + 1, line, match.index + 1 + match[0].length),
          options: { inlineClassName: `ov-link ov-link-${node.type}` },
        })
      }
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
  }, [code, hints, resolve, describe])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || !revealLine) return
    editor.revealLineInCenter(revealLine.line)
    editor.setSelection(new monaco.Range(revealLine.line, 1, revealLine.line, 1))
    editor.focus()
  }, [revealLine])

  return <div ref={host} className="h-full w-full" />
}

export function describeNode(node: GraphNode, extra: string): string {
  return `**${node.name}**  \n${TYPES[node.type].label} - id ${node.ref}${extra ? `  \n${extra}` : ''}  \n\n_Click to open_`
}
