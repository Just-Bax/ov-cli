import type {
  CodeSection,
  DatadogDiscovery,
  DatadogStatus,
  GraphStatus,
  Instance,
  InstanceGraph,
  InstanceHealth,
  ModelInfo,
  ObjectActivity,
  PagerDutyWebsites,
  PagerDutyStatus,
  Rating,
  RunInput,
  RunState,
  RunSummary,
  SavedTotals,
  Settings,
  SkillInfo,
  SourceInfo,
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

export interface SourceDraft {
  name: string
  description: string
  location: string
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
  models: () => request<ModelInfo[]>('/models'),
  instances: () => request<Instance[]>('/instances'),
  loginInstance: (url: string, tenant?: string, token?: string) =>
    post<{ ok: boolean; message: string }>('/instances/login', { url, tenant, token }),
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
  pagerdutyWebsites: (days = 7) => request<PagerDutyWebsites>(`/pagerduty/websites?days=${days}`),
  instanceHealth: (instance: string, range: string) =>
    request<InstanceHealth>(`/instance-health?instance=${seg(instance)}&range=${seg(range)}`),
  removeInstance: (alias: string) => post<Instance[]>('/instances/logout', { alias }),
  settings: () => request<Settings>('/settings'),
  saveSettings: (patch: Partial<Settings>) => put<Settings>('/settings', patch),
  skills: () => request<SkillInfo[]>('/skills'),
  createSkill: (draft: SkillDraft) => post<{ name: string; skills: SkillInfo[] }>('/skills', draft),
  updateSkill: (name: string, patch: Partial<SkillDraft & { enabled: boolean }>) =>
    put<SkillInfo[]>(`/skills/${seg(name)}`, patch),
  deleteSkill: (name: string) => del<SkillInfo[]>(`/skills/${seg(name)}`),
  sources: () => request<SourceInfo[]>('/sources'),
  addSource: (draft: SourceDraft) => post<SourceInfo[]>('/sources', draft),
  updateSource: (name: string, draft: Omit<SourceDraft, 'name'>) =>
    put<SourceInfo[]>(`/sources/${seg(name)}`, draft),
  syncSource: (name: string) => post<SourceInfo[]>(`/sources/${seg(name)}/sync`),
  deleteSource: (name: string) => del<SourceInfo[]>(`/sources/${seg(name)}`),
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
  runs: () => request<RunSummary[]>('/runs'),
  stats: () => request<SavedTotals>('/stats'),
  run: (id: string) => request<RunState>(`/runs/${id}`),
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
  deleteRun: (id: string) => del(`/runs/${id}`),
}
