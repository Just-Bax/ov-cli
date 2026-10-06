import 'monaco-editor/languages/definitions/python/register'
import 'monaco-editor/languages/definitions/java/register'
import 'monaco-editor/languages/definitions/javascript/register'
import 'monaco-editor/languages/definitions/typescript/register'
import 'monaco-editor/languages/definitions/xml/register'
import 'monaco-editor/languages/definitions/html/register'
import 'monaco-editor/languages/definitions/css/register'
import 'monaco-editor/languages/definitions/markdown/register'
import 'monaco-editor/languages/definitions/shell/register'
import 'monaco-editor/languages/definitions/powershell/register'
import 'monaco-editor/languages/definitions/bat/register'
import 'monaco-editor/languages/definitions/ini/register'

const LANGUAGES: Record<string, string> = {
  py: 'python',
  java: 'java',
  kt: 'java',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  xml: 'xml',
  pom: 'xml',
  html: 'html',
  htm: 'html',
  css: 'css',
  md: 'markdown',
  sh: 'shell',
  ps1: 'powershell',
  psm1: 'powershell',
  bat: 'bat',
  cmd: 'bat',
  ini: 'ini',
  properties: 'ini',
  toml: 'ini',
  cfg: 'ini',
  sql: 'sql',
  pks: 'sql',
  pkb: 'sql',
}

export function languageOf(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  return LANGUAGES[ext] ?? 'plaintext'
}
