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

export interface FileEdit {
  id: string
  toolId: string
  path: string
  created: boolean
  added: number
  removed: number
  before: string
  after: string
  truncated: boolean
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
  reply: string
}

export interface Question {
  id: string
  question: string
  options: string[]
  multiple: boolean
  answer?: string
  detail?: string
}

export interface LoginPrompt {
  id: string
  instance: string
  url: string
  tenant?: string
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
  | { type: 'edit'; edit: FileEdit }
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
  settled?: boolean
}

export type Rating = 'good' | 'off' | 'wrong'

export interface RunState {
  summary: RunSummary
  input: RunInput
  caseUrl?: string
  items: ThreadItem[]
  tools: ToolActivity[]
  changes: Change[]
  edits: FileEdit[]
  outcome?: Outcome
  outcomeId?: string
  questions: Question[]
  logins: LoginPrompt[]
  chat: ChatMessage[]
  error?: string
  feedback?: { rating: Rating; note: string }
  writeAccess: boolean
  queued: ChatMessage[]
  ratings: Record<string, { rating: Rating; note?: string }>
}

export interface Settings {
  defaultModel: string
  fastModel: string
  workspace: string
  workspaceNotes: string
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
  core: boolean
  builtin: boolean
  customized: boolean
  enabled: boolean
}

export interface WorkspaceEntry {
  name: string
  path: string
  dir: boolean
}

export interface WorkspaceEntries {
  root: string
  entries: WorkspaceEntry[]
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
  mode: 'session' | 'token'
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

export type DatadogArea = 'logs' | 'metrics' | 'monitors' | 'events' | 'apm' | 'hosts'

export interface DatadogStatus {
  connected: boolean
  site: string
  appUrl: string
  apiKeyLast4?: string | null
  appKeyLast4?: string | null
  permissions: Record<DatadogArea, boolean>
  checkedAt?: number | null
  error?: string | null
  matches: Record<string, string>
  sites: { id: string; app: string }[]
  scopes: string[]
}

export interface DatadogDiscovery {
  hosts: { name: string; role: string; alias: string | null }[]
  groups: Record<string, string>
}

export interface HealthServerMetric {
  latest: number
  max: number
  points: HealthPoint[]
}

export interface HealthServer {
  host: string
  role: string
  metrics: Partial<Record<'cpu' | 'memory' | 'disk' | 'load' | 'heap', HealthServerMetric>>
}

export interface HealthPoint {
  t: number
  v: number
}

export interface HealthMonitor {
  id: number
  name: string
  state: string
  type: string
  groups: string[]
  message: string
}

export interface HealthMeta {
  instance: string
  range: string
  scope: string
  from: number
  to: number
  appUrl: string
  links: { logs: string; monitors: string; apm: string; events: string; metrics: string }
}

export interface HealthEvent {
  time: string
  title: string
  message: string
  source: string
  status: string
}

export interface HealthSections {
  monitors: { monitors: HealthMonitor[] }
  logs: {
    errorSeries: HealthPoint[]
    logSeries: HealthPoint[]
    previousErrors: number
    topErrors: { pattern: string; count: number; example: string; service: string; last: string }[]
  }
  traffic: {
    traffic: { requests: HealthPoint[]; p95Ms: HealthPoint[] }
    slowEndpoints: { resource: string; p95Ms: number; count: number }[]
  }
  servers: { servers: HealthServer[] }
  events: { events: HealthEvent[] }
  onevizion: {
    byType: { type: string; count: number; last: string }[]
    failures: { type: string; at: string }[]
    utcOffsetMinutes: number
  }
  incidents: PagerDutyHealth
}

export type HealthSection = keyof HealthSections

export type SectionResult<K extends HealthSection> = HealthSections[K] | { unavailable: string }

export interface PagerDutyIncidentDetail extends PagerDutyIncident {
  timeline: { time: string; type: string; summary: string; by: string }[]
  alerts: { time: string; status: string; summary: string; details: string }[]
  notes: { time: string; by: string; text: string }[]
}

export type PagerDutyArea = 'incidents' | 'oncall'

export interface PagerDutyStatus {
  connected: boolean
  region: 'us' | 'eu'
  subdomain: string
  webUrl: string
  user?: string | null
  email?: string | null
  keyLast4?: string | null
  permissions: Record<PagerDutyArea, boolean>
  checkedAt?: number | null
  error?: string | null
}

export interface PagerDutyIncident {
  id: string
  number: number
  title: string
  status: string
  urgency: string
  priority: string
  service: string
  created: string
  changed: string
  assignees: string[]
  url: string
}

export interface PagerDutyHealth {
  webUrl?: string
  errors: Record<string, string>
  open?: PagerDutyIncident[]
  incidents?: PagerDutyIncident[]
  oncall?: { user: string; level: number; policy: string; schedule: string; until: string }[]
}
