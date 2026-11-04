export type RunStatus = 'queued' | 'running' | 'waiting' | 'done' | 'error' | 'cancelled'

export interface CommandVerdict {
  effect: 'read' | 'change' | 'outside' | 'write'
  reason: string
}

export interface BrowserPointer {
  x: number
  y: number
  step: number
  press?: boolean
}

export interface BrowserTab {
  index: number
  title: string
  url: string
  active: boolean
}

export interface BrowserDialog {
  kind: 'alert' | 'confirm' | 'prompt' | 'beforeunload'
  message: string
  default: string
}

export interface BrowserState {
  open: boolean
  instance?: string
  session?: number
  pointer?: BrowserPointer | null
  error?: string | null
  loading?: string | null
  tabs?: BrowserTab[]
  dialog?: BrowserDialog | null
}

export interface ToolActivity {
  id: string
  name: string
  label: string
  status: 'running' | 'ok' | 'error'
  input?: string
  output?: string
  ms?: number
  startedAt?: number
  backgroundedAt?: number
  stoppedAt?: number
  verdict?: CommandVerdict
  lazy?: boolean
}

export type ToolUpdate = Pick<ToolActivity, 'id'> & Partial<ToolActivity>

export interface FileEdit {
  id: string
  toolId: string
  path: string
  created: boolean
  added: number
  removed: number
  before?: string
  after?: string
  truncated: boolean
  lazy?: boolean
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

export type GridColumnType = 'text' | 'number' | 'date' | 'link' | 'trackor' | 'status' | 'change'

export interface GridColumn {
  key: string
  label: string
  type: GridColumnType
  href?: string
  idKey?: string
}

export interface CellChange {
  before: unknown
  after: unknown
}

export type GridRow = Record<string, unknown>

export type DataChangeState = 'proposed' | 'running' | 'done' | 'rejected' | 'blocked' | 'stopped'

export interface DataChange {
  state: DataChangeState
  trackorType: string
  fields: string[]
  total: number
  done: number
  updated: number
  failed: number
  unchanged: number
  revertOf?: string
}

export interface Grid {
  id: string
  title: string
  instance?: string
  baseUrl?: string
  columns: GridColumn[]
  rows: GridRow[]
  total: number
  ranAt: number
  source?: { kind: 'sql' | 'ov' }
  loading?: boolean
  error?: string | null
  change?: DataChange
}

export type GridUpdate = Pick<Grid, 'id'> & Partial<Grid>

export type Verdict = 'fix' | 'fixed' | 'user_action' | 'expected' | 'info' | 'unknown'

interface IssueFinding {
  title: string
  verdict: Verdict
  summary: string
  stillHappening?: boolean
  evidence?: string[]
}

interface ExistingMatch {
  key: string
  title: string
  covers: 'yes' | 'partly' | 'no'
  note?: string
  link?: string
}

export interface Outcome {
  issues: IssueFinding[]
  existing?: ExistingMatch[]
  unrelated: string[]
  reply: string
}

interface QuestionOption {
  label: string
  description?: string
}

export interface QuestionItem {
  header: string
  question: string
  options: QuestionOption[]
  multiple: boolean
}

interface QuestionBase {
  id: string
  toolId?: string
  answers?: string[]
  stopped?: boolean
}

export interface AskQuestion extends QuestionBase {
  kind: 'ask'
  items: QuestionItem[]
}

export interface ApprovalQuestion extends QuestionBase {
  kind: 'approval'
  question: string
  detail: string
  reason?: string
  note?: string
}

export type Question = AskQuestion | ApprovalQuestion

export interface LoginPrompt {
  id: string
  instance: string
  url: string
  tenant?: string
  state: 'needed' | 'running' | 'done' | 'failed' | 'skipped'
  message?: string
}

export interface MessageFile {
  name: string
  kind: 'image' | 'email' | 'text' | 'pdf' | 'other'
  localUrl?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  ts: number
  files?: MessageFile[]
  steer?: boolean
  links?: MessageLinks
  reasoning?: string
}

export interface MessageLinks {
  mentions: { text: string; url: string }[]
  unverified: string[]
}

export interface Compaction {
  id: string
  trigger: 'auto' | 'manual'
  status: 'running' | 'done' | 'error'
  startedAt: number
  before?: number
  after?: number
  ms?: number
  error?: string
}

export interface ContextUsage {
  tokens: number
  limit: number
  compactAt?: number
}

export type RunEvent =
  | { type: 'status'; status: RunStatus; error?: string }
  | {
      type: 'meta'
      title?: string
      caseKey?: string
      caseUrl?: string
      instance?: string
      continuedFrom?: ThreadLink
      continuedIn?: ThreadLink
    }
  | { type: 'tool'; tool: ToolUpdate }
  | { type: 'text'; messageId: string; delta: string }
  | { type: 'reasoning'; messageId: string; delta: string }
  | {
      type: 'message'
      messageId: string
      text: string
      ts?: number
      links?: MessageLinks
      reasoning?: string
    }
  | { type: 'user'; message: ChatMessage }
  | { type: 'change'; change: Change }
  | { type: 'grid'; grid: GridUpdate }
  | { type: 'edit'; edit: FileEdit }
  | { type: 'outcome'; outcome: Outcome }
  | { type: 'question'; question: Question }
  | { type: 'login'; login: LoginPrompt }
  | { type: 'access'; access: Access }
  | { type: 'browser'; browser: Partial<BrowserState> }
  | { type: 'queued'; message: ChatMessage }
  | { type: 'unqueue'; id: string }
  | { type: 'queue'; order: string[]; steering: string[]; held: boolean }
  | { type: 'rewind'; itemId: string }
  | { type: 'cost'; cost: CostTotal }
  | { type: 'compact'; compact: Compaction }
  | { type: 'context'; context: ContextUsage }

export type Provider = 'copilot' | 'claude' | 'openai'

export type CostUnit = 'credits' | 'usd' | 'tokens'

export interface CostTotal {
  amount: number
  requests: number
}

interface ModelCost extends CostTotal {
  model: string
  provider: Provider
}

export interface RunCost extends CostTotal {
  tokens: Record<string, number>
  models: ModelCost[]
}

export type CostRange = 'month' | '7d' | '30d'

export interface CostReport extends RunCost {
  days: ({ day: string } & CostTotal)[]
  threads: ({ id: string; title: string } & CostTotal)[]
}

export interface CopilotUser {
  signedIn: boolean
  user?: string | null
}

export interface OpenAIAccount {
  signedIn: boolean
  baseUrl: string | null
  hasKey: boolean
}

export type ProviderAccount = ClaudeAccount | CopilotUser | OpenAIAccount

export interface ProviderStatus {
  id: Provider
  name: string
  costUnit: CostUnit
  cacheTtlMs: number | null
  account: ProviderAccount
}

export interface ThreadLink {
  id: string
  title: string
}

export interface CopilotAccount {
  plan: string
  resetDate: string | null
  tokenBased: boolean
  creditsUsed: number | null
  unlimited: boolean
  entitlement: number | null
  remaining: number | null
}

export interface ClaudeAccount {
  installed: boolean
  signedIn: boolean
  email?: string
  plan?: string
  method?: string
}

export interface StoredEvent {
  seq: number
  ts: number
  live?: boolean
  event: RunEvent
}

export interface OutlineMark {
  kind: 'user' | 'agent'
  start: number
  label: string
}

export interface RunWindow {
  items: ThreadItem[]
  start: number
  chat: ChatMessage[]
  tools: ToolActivity[]
  changes: Change[]
  grids: Grid[]
  questions: Question[]
  logins: LoginPrompt[]
  compactions: Compaction[]
  outline: OutlineMark[]
}

export interface RunDetails {
  tools: Record<string, { input?: string; output?: string }>
  edits: Record<string, { before?: string; after?: string }>
}

export type ThreadItem =
  | { kind: 'user'; id: string }
  | { kind: 'text'; id: string }
  | { kind: 'tool'; id: string }
  | { kind: 'change'; id: string }
  | { kind: 'grid'; id: string }
  | { kind: 'question'; id: string }
  | { kind: 'login'; id: string }
  | { kind: 'outcome'; id: string }
  | { kind: 'compact'; id: string }

export interface Upload {
  id: string
  name: string
}

export type Access = 'read' | 'ask' | 'auto' | 'full'

export interface RunInput {
  prompt: string
  instance?: string
  attachments?: Upload[]
  access?: Access
}

export type Attention = 'done' | 'failed' | 'woke'

export interface RunSummary {
  id: string
  title: string
  caseKey?: string
  instance?: string
  status: RunStatus
  provider: Provider
  model: string
  createdAt: number
  updatedAt: number
  settled?: boolean
  pinned?: boolean
  snoozedUntil?: number
  attention?: Attention
  cost?: CostTotal
}

export interface RunList {
  active: RunSummary[]
  snoozed: RunSummary[]
  settled: RunSummary[]
  settledTotal: number
}

export interface RunState extends RunWindow {
  summary: RunSummary
  input: RunInput
  caseUrl?: string
  edits: FileEdit[]
  outcome?: Outcome
  outcomeId?: string
  error?: string
  access: Access
  queued: ChatMessage[]
  queueHeld: boolean
  instances: string[]
  browser?: BrowserState
  context?: ContextUsage
  continuedFrom?: ThreadLink
  continuedIn?: ThreadLink
}

export type RunSnapshot = RunState & { seq: number }

export interface Settings {
  provider: Provider
  defaultModel: string
  fastModel: string
  workspace: string
  workspaceNotes: string
  fullName: string
  instructions: string
  maxSteps: number
  reasoning: ReasoningLevel | ''
  notify: boolean
  tabBadge: boolean
}

export interface SkillInfo {
  name: string
  source: 'bundled' | 'custom'
  title: string
  description: string
  content: string
  core: boolean
  enabled: boolean
}

export interface ModelInfo {
  id: string
  name: string
  vendor: string
  vision: boolean
  premium?: number
  reasoning: ReasoningLevel[]
  description?: string
  contextWindow?: number | null
  reportedWindow?: number | null
}

export type FollowUp = 'steer' | 'queue'

export type ReasoningLevel = 'none' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export type PlatformEdition = 'STANDARD' | 'ENTERPRISE' | 'PREMIUM' | 'AI_ENABLED'

export interface InstanceAccess {
  checking: boolean
  error?: string
  checkedAt?: number
  version?: string | null
  edition?: PlatformEdition | null
  testSql?: boolean
  export?: boolean
  import?: boolean
  metadata?: boolean
  dbSource?: boolean
  mcp?: boolean
}

export interface Instance {
  alias: string
  url: string
  host: string
  tenant?: string
  current: boolean
  expires?: string
  valid: boolean
  mode: 'session' | 'token' | 'remembered'
  access: InstanceAccess
}

export interface Status {
  provider: Provider
  providers: ProviderStatus[]
  ov: { version: string }
  instances: { total: number; valid: number }
  settings: Settings
  ready: boolean
  fullAccess: boolean
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

export type GraphSource = 'sql' | 'export'

export interface InstanceGraph {
  instance: string
  host: string
  builtAt: number
  source?: GraphSource
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
  source?: GraphSource | null
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
  databases: Record<string, string[]>
  sites: { id: string; app: string }[]
  scopes: string[]
}

export interface DatadogDatabase {
  id: string
  engine: string
  endpoint: string
}

export interface DatadogDatabaseDiscovery {
  databases: DatadogDatabase[]
  groups: Record<string, string[]>
}

export interface DatadogDiscovery {
  hosts: { name: string; role: string; alias: string | null }[]
  groups: Record<string, string>
}

interface HealthServerMetric {
  latest: number
  max: number
  points: HealthPoint[]
}

export interface HealthServer {
  host: string
  role: string
  metrics: Partial<Record<'cpu' | 'memory' | 'disk' | 'load' | 'heap', HealthServerMetric>>
}

export type HealthDatabaseMetricKey =
  | 'cpu'
  | 'memory'
  | 'storage'
  | 'connections'
  | 'readLatency'
  | 'writeLatency'
  | 'activeSessions'
  | 'responseTime'
  | 'sessions'
  | 'tablespace'

interface HealthDatabase extends DatadogDatabase {
  shared: boolean
  metrics: Partial<Record<HealthDatabaseMetricKey, HealthServerMetric>>
}

export interface HealthPoint {
  t: number
  v: number
}

interface HealthMonitor {
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

interface HealthEvent {
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
  database: { databases: HealthDatabase[] }
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

interface PagerDutyHealth {
  webUrl?: string
  errors: Record<string, string>
  open?: PagerDutyIncident[]
  incidents?: PagerDutyIncident[]
  oncall?: { user: string; level: number; policy: string; schedule: string; until: string }[]
}
