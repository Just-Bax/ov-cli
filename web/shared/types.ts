export type RunStatus = 'queued' | 'running' | 'waiting' | 'done' | 'error' | 'cancelled'

export interface ToolActivity {
  id: string
  name: string
  label: string
  status: 'running' | 'ok' | 'error'
  input?: string
  output?: string
  ms?: number
}

export interface Change {
  id: string
  title: string
  entityType: string
  entityId?: string
  entityName?: string
  instance?: string
  link?: string
  language: string
  before: string
  after: string
  what: string
  why: string
  how: string
}

export type Verdict = 'fix' | 'fixed' | 'user_action' | 'expected' | 'info' | 'unknown'

export interface IssueFinding {
  title: string
  verdict: Verdict
  summary: string
  stillHappening?: boolean
  evidence?: string[]
}

export interface ExistingMatch {
  key: string
  title: string
  covers: 'yes' | 'partly' | 'no'
  note?: string
  link?: string
}

export interface TimeSaved {
  minutes: number
  basis: string
}

export interface Outcome {
  timeSaved?: TimeSaved
  issues: IssueFinding[]
  existing?: ExistingMatch[]
  unrelated: string[]
  /** The case chat comment, or a message to forward; empty when there is none. */
  reply: string
}

export interface Question {
  id: string
  question: string
  options: string[]
  multiple: boolean
  answer?: string
  /** Exact change awaiting approval, shown as code. */
  detail?: string
}

export interface LoginPrompt {
  id: string
  instance: string
  url: string
  state: 'needed' | 'running' | 'done' | 'failed'
  message?: string
}

export interface MessageFile {
  name: string
  kind: 'image' | 'email' | 'text' | 'pdf' | 'other'
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  ts: number
  files?: MessageFile[]
}

export type RunEvent =
  | { type: 'status'; status: RunStatus; error?: string }
  | { type: 'meta'; title?: string; caseKey?: string; caseUrl?: string; instance?: string }
  | { type: 'tool'; tool: ToolActivity }
  | { type: 'text'; messageId: string; delta: string }
  | { type: 'user'; message: ChatMessage }
  | { type: 'change'; change: Change }
  | { type: 'outcome'; outcome: Outcome }
  | { type: 'question'; question: Question }
  | { type: 'login'; login: LoginPrompt }
  | { type: 'usage'; requests: number }
  | { type: 'access'; write: boolean }
  | { type: 'queued'; message: ChatMessage }
  | { type: 'unqueue'; id: string }
  | { type: 'rewind'; itemId: string }
  | { type: 'rate'; turnId: string; rating: Rating | null; note?: string }

export interface StoredEvent {
  seq: number
  ts: number
  event: RunEvent
}

/** The thread in display order; each entry points into the matching collection. */
export type ThreadItem =
  | { kind: 'user'; id: string }
  | { kind: 'text'; id: string }
  | { kind: 'tool'; id: string }
  | { kind: 'change'; id: string }
  | { kind: 'question'; id: string }
  | { kind: 'login'; id: string }
  | { kind: 'outcome'; id: string }

export interface Upload {
  id: string
  name: string
}

export interface RunInput {
  prompt: string
  instance?: string
  attachments?: Upload[]
  model?: string
  allowWrite?: boolean
}

export interface RunSummary {
  id: string
  title: string
  caseKey?: string
  instance?: string
  status: RunStatus
  model: string
  createdAt: number
  updatedAt: number
  rating?: Rating
}

export type Rating = 'good' | 'off' | 'wrong'

export interface RunState {
  summary: RunSummary
  input: RunInput
  caseUrl?: string
  items: ThreadItem[]
  tools: ToolActivity[]
  changes: Change[]
  outcome?: Outcome
  outcomeId?: string
  questions: Question[]
  logins: LoginPrompt[]
  chat: ChatMessage[]
  error?: string
  feedback?: { rating: Rating; note: string }
  writeAccess: boolean
  /** Follow-ups sent while the agent was busy, waiting to be picked up. */
  queued: ChatMessage[]
  /** Per-turn ratings, keyed by the user message that started the turn. */
  ratings: Record<string, { rating: Rating; note?: string }>
}

export interface Settings {
  defaultModel: string
  maxSteps: number
  notify: boolean
  showTimeSaved: boolean
  expandTools: boolean
}

export interface SavedTotals {
  week: { minutes: number; runs: number }
  month: { minutes: number; runs: number }
  all: { minutes: number; runs: number }
}

export interface SkillInfo {
  name: string
  title: string
  description: string
  content: string
  builtin: boolean
  customized: boolean
  enabled: boolean
}

export interface SourceInfo {
  name: string
  description: string
  location: string
  kind: 'git' | 'folder'
  path: string
  ready: boolean
}

export interface ModelInfo {
  id: string
  name: string
  vendor: string
  vision: boolean
  premium?: number
}

export interface Instance {
  alias: string
  url: string
  host: string
  tenant?: string
  current: boolean
  expires?: string
  valid: boolean
}

export interface Status {
  copilot: { signedIn: boolean; user?: string }
  ov: { version: string }
  instances: { total: number; valid: number }
  settings: Settings
  ready: boolean
}

export type GraphNodeType =
  | 'trackor_type'
  | 'field'
  | 'rule'
  | 'automation'
  | 'import'
  | 'report'
  | 'notification'
  | 'workflow'
  | 'module'
  | 'db_package'

export interface GraphNode {
  id: string
  type: GraphNodeType
  ref: number
  name: string
  enabled?: boolean
  invalid?: boolean
  trigger?: string
  dataType?: number
  async?: boolean
  filtered?: boolean
}

export interface GraphEdge {
  source: string
  target: string
  kind: string
  code?: boolean
}

export interface InstanceGraph {
  instance: string
  host: string
  builtAt: number
  warnings: string[]
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GraphStatus {
  state: 'none' | 'building' | 'ready' | 'error'
  step?: string
  error?: string
  builtAt?: number
  nodes?: number
  edges?: number
}

export interface CodeHint {
  line: number
  severity: 'error' | 'warn' | 'info'
  title: string
  detail: string
}

export interface CodeSection {
  title: string
  code: string
  hints: CodeHint[]
}

export interface ObjectActivity {
  ts?: string
  status?: string
  runtime?: string
  message?: string
}
