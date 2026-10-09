import type {
  CodeSection,
  CopilotAccount,
  CostRange,
  CostReport,
  RunCost,
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
  ObjectActivity,
  PagerDutyStatus,
  Rating,
  RunInput,
  RunDetails,
  RunSnapshot,
  RunWindow,
  RunList,
  SavedTotals,
  Settings,
  SkillInfo,
  WorkspaceEntries,
  Status,
  Upload,
} from '@shared/types.ts'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok)
    throw new Error((body as { error?: string }).error ?? `${res.status} ${res.statusText}`)
  return body as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' })
const seg = encodeURIComponent

export interface SkillDraft {
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
  cost: (range: CostRange) => request<CostReport>(`/cost?range=${range}`),
  runCost: (id: string) => request<RunCost>(`/runs/${id}/cost`),
  exportUrl: (id: string) => `/api/runs/${id}/export`,
  models: () => request<ModelInfo[]>('/models'),
  instances: () => request<Instance[]>('/instances'),
  loginInstance: (
    url: string,
    tenant?: string,
    token?: string,
    screen?: { width: number; height: number },
  ) => post<{ ok: boolean; message: string }>('/instances/login', { url, tenant, token, screen }),
  cancelSignIn: (url: string, tenant?: string) =>
    post(`/signin/cancel?url=${seg(url)}&tenant=${seg(tenant ?? '')}`),
  datadog: () => request<DatadogStatus>('/datadog'),
  datadogConnect: (site: string, apiKey: string, appKey: string) =>
    post<DatadogStatus>('/datadog/connect', { site, apiKey, appKey }),
  datadogTest: () => post<DatadogStatus>('/datadog/test', {}),
  datadogDisconnect: () => del<DatadogStatus>('/datadog'),
  datadogDiscover: () => request<DatadogDiscovery>('/datadog/discover'),
  datadogMatches: (matches: Record<string, string>) =>
    put<DatadogStatus>('/datadog/matches', { matches }),
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
  workspaceEntries: (path: string) =>
    request<WorkspaceEntries>(`/workspace/entries?path=${seg(path)}`),
  workspaceFile: (path: string) =>
    request<{ path: string; content: string }>(`/workspace/file?path=${seg(path)}`),
  saveWorkspaceFile: (path: string, content: string) =>
    put<{ path: string; content: string }>('/workspace/file', { path, content }),
  removeInstance: (alias: string) => post<Instance[]>('/instances/logout', { alias }),
  settings: () => request<Settings>('/settings'),
  saveSettings: (patch: Partial<Settings>) => put<Settings>('/settings', patch),
  skills: () => request<SkillInfo[]>('/skills'),
  createSkill: (draft: SkillDraft) => post<{ name: string; skills: SkillInfo[] }>('/skills', draft),
  updateSkill: (name: string, patch: Partial<SkillDraft & { enabled: boolean }>) =>
    put<SkillInfo[]>(`/skills/${seg(name)}`, patch),
  deleteSkill: (name: string) => del<SkillInfo[]>(`/skills/${seg(name)}`),
  upload: async (files: File[]) => {
    const saved: Upload[] = []
    for (const file of files) {
      saved.push(
        await request<Upload>('/uploads', {
          method: 'POST',
          body: file,
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-File-Name': encodeURIComponent(file.name || 'pasted.png'),
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
  runs: (settled: number) => request<RunList>(`/runs?settled=${settled}`),
  stats: () => request<SavedTotals>('/stats'),
  run: (id: string, turns: number) => request<RunSnapshot>(`/runs/${id}?turns=${turns}`),
  runHistory: (id: string, end: number, turns: number) =>
    request<RunWindow>(`/runs/${id}/history?end=${end}&turns=${turns}`),
  runDetails: (id: string, tools: string[], edits: string[]) =>
    request<RunDetails>(
      `/runs/${id}/details?tools=${tools.map(seg).join(',')}&edits=${edits.map(seg).join(',')}`,
    ),
  startRun: (input: RunInput) => post<{ id: string }>('/runs', input),
  answer: (id: string, questionId: string, answer: string) =>
    post(`/runs/${id}/answer`, { questionId, answer }),
  login: (id: string, loginId: string, skip = false) =>
    post(`/runs/${id}/login`, { loginId, skip }),
  message: (id: string, text: string, files: Upload[] = []) =>
    post(`/runs/${id}/message`, { text, files }),
  retry: (id: string, itemId: string) => post(`/runs/${id}/retry`, { itemId }),
  renameRun: (id: string, title: string) => post(`/runs/${id}/title`, { title }),
  removeQueued: (id: string, mid: string) => del(`/runs/${id}/queued/${seg(mid)}`),
  rate: (id: string, turnId: string, rating: Rating | null, note?: string) =>
    post(`/runs/${id}/rate`, { turnId, rating, note }),
  fileUrl: (id: string, name: string) => `/api/runs/${id}/files/${seg(name)}`,
  setWriteAccess: (id: string, write: boolean) => post(`/runs/${id}/access`, { write }),
  cancel: (id: string) => post(`/runs/${id}/cancel`),
  feedback: (id: string, rating: Rating, note: string) =>
    post(`/runs/${id}/feedback`, { rating, note }),
  settleRun: (id: string, settled: boolean) => post(`/runs/${id}/settle`, { settled }),
}
