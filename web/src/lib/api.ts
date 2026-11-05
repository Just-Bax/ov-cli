import type {
  Access,
  FollowUp,
  CodeSection,
  MessageFile,
  ClaudeAccount,
  CopilotAccount,
  CostRange,
  CostReport,
  RunCost,
  DatadogDatabase,
  DatadogDatabaseDiscovery,
  DatadogDiscovery,
  DatadogStatus,
  GraphStatus,
  Instance,
  InstanceGraph,
  HealthMeta,
  HealthSection,
  SectionResult,
  PagerDutyIncidentDetail,
  ModelInfo,
  OpenAIAccount,
  Provider,
  ObjectActivity,
  PagerDutyStatus,
  RunInput,
  RunDetails,
  RunSnapshot,
  RunWindow,
  RunList,
  Settings,
  SkillInfo,
  Status,
  Upload,
  RunSummary,
  SearchHit,
} from '@shared/types.ts'

const API_ROOT = '/api'
const UNNAMED_UPLOAD = 'pasted.png'

function errorIn(text: string): string | undefined {
  if (!text.startsWith('{')) return undefined
  return (JSON.parse(text) as { error?: string }).error
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })

  const text = await res.text()
  if (!res.ok) throw new Error(errorIn(text) ?? `${res.status} ${res.statusText}`)

  return JSON.parse(text) as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' })
const seg = encodeURIComponent
const signInQuery = (url: string, tenant?: string) => `url=${seg(url)}&tenant=${seg(tenant ?? '')}`

interface SkillDraft {
  title: string
  description: string
  content: string
}

export const api = {
  status: () => request<Status>('/status'),
  deviceStart: () =>
    post<{ deviceCode: string; userCode: string; verificationUri: string; interval: number }>(
      '/copilot/device',
    ),
  devicePoll: (deviceCode: string) =>
    post<{ status: 'pending' | 'slow_down' | 'ok' | 'error'; message?: string; user?: string }>(
      '/copilot/poll',
      { deviceCode },
    ),
  copilotLogout: () => post('/copilot/logout'),
  copilotAccount: () => request<CopilotAccount>('/copilot/account'),
  cost: (range: CostRange, provider: Provider) =>
    request<CostReport>(`/cost?range=${range}&provider=${provider}`),
  compactRun: (id: string) => post(`/threads/${id}/compact`),
  branch: (id: string, before?: string) =>
    post<{ id: string }>(`/threads/${id}/branch`, { before: before ?? null }),
  retryAsBranch: (id: string, itemId: string) =>
    post<{ id: string }>(`/threads/${id}/retry-branch`, { itemId }),
  branches: (id: string) => request<{ branches: RunSummary[] }>(`/threads/${id}/branches`),
  searchThreads: (q: string, signal?: AbortSignal) =>
    request<{ threads: SearchHit[] }>(`/search?q=${seg(q)}`, { signal }),
  pinRun: (id: string, pinned: boolean) => post(`/threads/${id}/pin`, { pinned }),
  snoozeRun: (id: string, until: number | null) => post(`/threads/${id}/snooze`, { until }),
  markRunSeen: (id: string) => post(`/threads/${id}/seen`),
  searchRun: (id: string, q: string, signal?: AbortSignal) =>
    request<{ items: number[] }>(`/threads/${id}/search?q=${seg(q)}`, { signal }),
  runCost: (id: string) => request<RunCost>(`/threads/${id}/cost`),
  exportUrl: (id: string) => `${API_ROOT}/threads/${id}/export`,
  runEventsUrl: (id: string, after: number) => `${API_ROOT}/threads/${id}/events?after=${after}`,
  statusEventsUrl: () => `${API_ROOT}/status-events`,
  models: (provider: Provider) => request<ModelInfo[]>(`/models?provider=${provider}`),
  claudeAccount: () => request<ClaudeAccount>('/claude/account'),
  openaiConnect: (baseUrl: string, apiKey: string) =>
    post<OpenAIAccount>('/openai/connect', { baseUrl, apiKey }),
  openaiDisconnect: () => post<OpenAIAccount>('/openai/disconnect'),
  openaiConfigureModel: (id: string, vision: boolean, contextWindow: number | null) =>
    put<ModelInfo[]>('/openai/models', { id, vision, contextWindow }),
  instances: () => request<Instance[]>('/instances'),
  loginInstance: (
    url: string,
    tenant?: string,
    token?: string,
    screen?: { width: number; height: number },
    remember?: boolean,
  ) =>
    post<{ ok: boolean; message: string }>('/instances/login', {
      url,
      tenant,
      token,
      screen,
      remember,
    }),
  cancelSignIn: (url: string, tenant?: string) =>
    post(`/signin/cancel?${signInQuery(url, tenant)}`),
  signInInput: (url: string, tenant: string | undefined, events: unknown[]) =>
    post<{ open: boolean }>(`/signin/input?${signInQuery(url, tenant)}`, { events }),
  signInScreenUrl: (url: string, tenant?: string) =>
    `${API_ROOT}/signin/screen?${signInQuery(url, tenant)}`,
  datadog: () => request<DatadogStatus>('/datadog'),
  datadogConnect: (site: string, apiKey: string, appKey: string) =>
    post<DatadogStatus>('/datadog/connect', { site, apiKey, appKey }),
  datadogTest: () => post<DatadogStatus>('/datadog/test', {}),
  datadogDisconnect: () => del<DatadogStatus>('/datadog'),
  datadogDiscover: () => request<DatadogDiscovery>('/datadog/discover'),
  datadogMatches: (matches: Record<string, string>) =>
    put<DatadogStatus>('/datadog/matches', { matches }),
  datadogDatabases: () => request<{ databases: DatadogDatabase[] }>('/datadog/databases'),
  datadogDiscoverDatabases: (matches: Record<string, string>) =>
    post<DatadogDatabaseDiscovery>('/datadog/databases/discover', { matches }),
  datadogPickDatabases: (databases: Record<string, string[]>) =>
    put<DatadogStatus>('/datadog/databases', { databases }),
  pagerduty: () => request<PagerDutyStatus>('/pagerduty'),
  pagerdutyConnect: (account: string, apiKey: string) =>
    post<PagerDutyStatus>('/pagerduty/connect', { account, apiKey }),
  pagerdutyTest: () => post<PagerDutyStatus>('/pagerduty/test', {}),
  pagerdutyDisconnect: () => del<PagerDutyStatus>('/pagerduty'),
  healthMeta: (instance: string, range: string) =>
    request<HealthMeta>(`/instance-health/meta?instance=${seg(instance)}&range=${seg(range)}`),
  healthSection: <K extends HealthSection>(
    section: K,
    instance: string,
    range: string,
    to: number,
  ) =>
    request<SectionResult<K>>(
      `/instance-health/${section}?instance=${seg(instance)}&range=${seg(range)}&to=${to}`,
    ),
  pagerdutyIncident: (id: string) =>
    request<PagerDutyIncidentDetail>(`/pagerduty/incidents/${seg(id)}`),
  removeInstance: (alias: string) => post<Instance[]>('/instances/logout', { alias }),
  rememberInstance: (alias: string) => post<Instance[]>('/instances/remember', { alias }),
  checkAccess: (alias: string) => post<Instance[]>('/instances/access', { alias }),
  saveSettings: (patch: Partial<Settings>) => put<Settings>('/settings', patch),
  skills: () => request<SkillInfo[]>('/skills'),
  createSkill: (draft: SkillDraft) => post<{ name: string; skills: SkillInfo[] }>('/skills', draft),
  updateSkill: (name: string, patch: Partial<SkillDraft & { enabled: boolean }>) =>
    put<SkillInfo[]>(`/skills/${seg(name)}`, patch),
  deleteSkill: (name: string) => del<SkillInfo[]>(`/skills/${seg(name)}`),
  cloneSkill: (name: string) =>
    post<{ name: string; skills: SkillInfo[] }>(`/skills/${seg(name)}/clone`),
  upload: async (files: File[]) => {
    const saved: Upload[] = []
    for (const file of files) {
      saved.push(
        await request<Upload>('/uploads', {
          method: 'POST',
          body: file,
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-File-Name': encodeURIComponent(file.name || UNNAMED_UPLOAD),
          },
        }),
      )
    }

    return saved
  },
  graphStatus: (instance: string) =>
    request<GraphStatus>(`/graph/status?instance=${seg(instance)}`),
  buildGraph: (instance: string) => post<GraphStatus>('/graph/build', { instance }),
  graph: (instance: string) => request<InstanceGraph>(`/graph?instance=${seg(instance)}`),
  source: (instance: string, id: string) =>
    request<{ sections: CodeSection[] }>(
      `/explorer/source?instance=${seg(instance)}&id=${seg(id)}`,
    ),
  activity: (instance: string, id: string) =>
    request<ObjectActivity[]>(`/explorer/activity?instance=${seg(instance)}&id=${seg(id)}`),
  runs: (settled: number) => request<RunList>(`/threads?settled=${settled}`),
  run: (id: string, turns: number) => request<RunSnapshot>(`/threads/${id}?turns=${turns}`),
  runHistory: (id: string, end: number, turns: number) =>
    request<RunWindow>(`/threads/${id}/history?end=${end}&turns=${turns}`),
  runDetails: (id: string, tools: string[], edits: string[]) =>
    request<RunDetails>(
      `/threads/${id}/details?tools=${tools.map(seg).join(',')}&edits=${edits.map(seg).join(',')}`,
    ),
  startRun: (input: RunInput) => post<{ id: string }>('/threads', input),
  answer: (id: string, questionId: string, answers: string[], note = '') =>
    post(`/threads/${id}/answer`, { questionId, answers, note }),
  login: (
    id: string,
    loginId: string,
    options: {
      skip?: boolean
      token?: string
      screen?: { width: number; height: number }
      remember?: boolean
    } = {},
  ) => post<{ ok: boolean; message: string }>(`/threads/${id}/login`, { loginId, ...options }),
  message: (id: string, messageId: string, text: string, files: Upload[], mode: FollowUp) =>
    post(`/threads/${id}/message`, { id: messageId, text, files, mode }),
  moveQueued: (id: string, mid: string, before: string | null) =>
    post(`/threads/${id}/queued/${seg(mid)}/move`, { before }),
  resumeQueue: (id: string) => post(`/threads/${id}/queue/resume`),
  sendQueued: (id: string, mid: string) => post(`/threads/${id}/queued/${seg(mid)}/send`),
  editQueued: (id: string, mid: string, text: string) =>
    post(`/threads/${id}/queued/${seg(mid)}/text`, { text }),
  retry: (id: string, itemId: string) => post(`/threads/${id}/retry`, { itemId }),
  renameRun: (id: string, title: string) => post(`/threads/${id}/title`, { title }),
  rerunGrid: (id: string, gridId: string) => post(`/threads/${id}/grids/${seg(gridId)}/rerun`),
  revertGrid: (id: string, gridId: string) => post(`/threads/${id}/grids/${seg(gridId)}/revert`),
  removeQueued: (id: string, mid: string) => del(`/threads/${id}/queued/${seg(mid)}`),
  fileUrl: (id: string, name: string) => `${API_ROOT}/threads/${id}/files/${seg(name)}`,
  imageUrl: (id: string, file: MessageFile) =>
    file.localUrl ?? `${API_ROOT}/threads/${id}/files/${seg(file.name)}`,
  setAccess: (id: string, access: Access) => post(`/threads/${id}/access`, { access }),
  cancel: (id: string) => post(`/threads/${id}/cancel`),
  browserScreenUrl: (id: string) => `${API_ROOT}/threads/${id}/browser/screen`,
  browserInput: (id: string, events: unknown[]) =>
    post<{ open: boolean }>(`/threads/${id}/browser/input`, { events }),
  closeBrowser: (id: string) => post(`/threads/${id}/browser/close`),
  answerBrowserDialog: (id: string, accept: boolean, text: string) =>
    post(`/threads/${id}/browser/dialog`, { accept, text }),
  browserTab: (id: string, index: number, close: boolean) =>
    post(`/threads/${id}/browser/tab`, { index, close }),
  resizeBrowser: (id: string, size: { width: number; height: number }) =>
    post(`/threads/${id}/browser/size`, size),
  openBrowser: (id: string, instance: string) => post(`/threads/${id}/browser/open`, { instance }),
  backgroundTool: (id: string, toolId: string) =>
    post(`/threads/${id}/tools/${seg(toolId)}/background`, {}),
  stopTool: (id: string, toolId: string) => post(`/threads/${id}/tools/${seg(toolId)}/stop`, {}),
  settleRun: (id: string, settled: boolean) => post(`/threads/${id}/settle`, { settled }),
  deleteRun: (id: string) => del<{ ok: boolean }>(`/threads/${id}`),
}
