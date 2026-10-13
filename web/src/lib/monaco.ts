import * as monaco from 'monaco-editor/editor/editor.api'
import 'monaco-editor/editor/browser/coreCommands'
import 'monaco-editor/editor/browser/widget/codeEditor/codeEditorWidget'
import 'monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching'
import 'monaco-editor/editor/contrib/clipboard/browser/clipboard'
import 'monaco-editor/editor/contrib/contextmenu/browser/contextmenu'
import 'monaco-editor/editor/contrib/find/browser/findController'
import 'monaco-editor/features/find/register'
import 'monaco-editor/editor/contrib/folding/browser/folding'
import 'monaco-editor/editor/contrib/gotoError/browser/gotoError'
import 'monaco-editor/editor/contrib/hover/browser/hoverContribution'
import 'monaco-editor/editor/contrib/lineSelection/browser/lineSelection'
import 'monaco-editor/editor/contrib/smartSelect/browser/smartSelect'
import 'monaco-editor/editor/contrib/stickyScroll/browser/stickyScrollContribution'
import 'monaco-editor/editor/contrib/wordHighlighter/browser/wordHighlighter'
import 'monaco-editor/editor/standalone/browser/quickAccess/standaloneGotoLineQuickAccess'
import 'monaco-editor/editor/common/standaloneStrings'
import 'monaco-editor/languages/definitions/sql/register'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'
import '../../node_modules/monaco-editor/esm/vs/base/browser/ui/codicons/codicon/codicon.css'

self.MonacoEnvironment = { getWorker: () => new EditorWorker() }

export const EDITOR_FONT = {
  fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
  fontSize: 12.5,
}

export const EDITOR_PADDING = { top: 12, bottom: 12 }

monaco.editor.defineTheme('ov-light', {
  base: 'vs',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: '7e57c2', fontStyle: 'bold' },
    { token: 'operator', foreground: '546e7a' },
    { token: 'string', foreground: '2e7d32' },
    { token: 'number', foreground: 'ef6c00' },
    { token: 'comment', foreground: '90a4ae', fontStyle: 'italic' },
    { token: 'predefined', foreground: '1e88e5' },
    { token: 'identifier', foreground: '263238' },
  ],
  colors: {
    'editor.background': '#ffffff',
    'editor.lineHighlightBackground': '#f4f6f7',
    'editor.lineHighlightBorder': '#00000000',
    'editor.selectionBackground': '#bbdefb',
    'editor.inactiveSelectionBackground': '#e1f5fe',
    'editorLineNumber.foreground': '#b0bec5',
    'editorLineNumber.activeForeground': '#546e7a',
    'editorIndentGuide.background1': '#eceff1',
    'editorGutter.background': '#ffffff',
    'scrollbarSlider.background': '#cfd8dc80',
    'scrollbarSlider.hoverBackground': '#b0bec5aa',
    'minimap.background': '#fafbfb',
    'editorStickyScroll.background': '#ffffff',
    'editorStickyScrollHover.background': '#f4f6f7',
    'editorHoverWidget.background': '#ffffff',
    'editorHoverWidget.border': '#cfd8dc',
    'editorWidget.background': '#ffffff',
    'editorWidget.border': '#cfd8dc',
  },
})

export { monaco }
