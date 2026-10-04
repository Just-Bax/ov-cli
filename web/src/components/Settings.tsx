import {
  FolderGit2,
  KeyRound,
  LogOut,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Trash2,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Instance, Settings, SkillInfo, SourceInfo } from '@shared/types.ts'
import { dialog } from '@/components/Dialog'
import { useModels } from '@/components/ModelPicker'
import {
  Button,
  Card,
  GithubMark,
  IconButton,
  Input,
  Label,
  Page,
  Select,
  Skeleton,
  SkeletonText,
  Spinner,
  Textarea,
} from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

function Section({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="grid gap-6 py-6 md:grid-cols-[200px_1fr]">
      <div>
        <div className="text-fg text-[13.5px] font-semibold">{title}</div>
        {hint ? <div className="text-muted mt-1 text-[12px] leading-relaxed">{hint}</div> : null}
      </div>
      <div>{children}</div>
    </section>
  )
}

function Preferences({ onChange }: { onChange: () => void }) {
  const [settings, setSettings] = useState<Settings>()
  const [instances, setInstances] = useState<Instance[]>([])
  const [saving, setSaving] = useState(false)
  const models = useModels()

  useEffect(() => {
    api
      .settings()
      .then(setSettings)
      .catch(() => undefined)
    api
      .instances()
      .then(setInstances)
      .catch(() => undefined)
  }, [])

  if (!settings) {
    return (
      <Card className="space-y-3 p-5">
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-7 w-2/3" />
      </Card>
    )
  }
  const set = (patch: Partial<Settings>) => setSettings({ ...settings, ...patch })

  return (
    <Card className="grid gap-4 p-5">
      <div className="grid gap-4 sm:grid-cols-[1fr_1fr_120px]">
        <div>
          <Label>Default model</Label>
          <Select
            className="w-full"
            value={settings.defaultModel}
            onChange={(v) => set({ defaultModel: v })}
            options={models.map((m) => ({
              value: m.id,
              label: `${m.name}${m.premium ? ` (x${m.premium})` : ''}`,
            }))}
          />
        </div>
        <div>
          <Label>Default instance</Label>
          <Select
            className="w-full"
            value={settings.defaultInstance}
            onChange={(v) => set({ defaultInstance: v })}
            placeholder="The current ov instance"
            options={[
              { value: '', label: 'The current ov instance' },
              ...instances.map((i) => ({ value: i.alias, label: i.alias, hint: i.host })),
            ]}
          />
        </div>
        <div>
          <Label>Max steps</Label>
          <Input
            type="number"
            min={10}
            max={300}
            value={settings.maxSteps}
            onChange={(e) => set({ maxSteps: Number(e.target.value) })}
          />
        </div>
      </div>
      <div>
        <Button
          variant="primary"
          disabled={saving}
          onClick={async () => {
            setSaving(true)
            setSettings(await api.saveSettings(settings))
            setSaving(false)
            onChange()
          }}
        >
          {saving ? <Spinner /> : <Save className="size-4" />} Save
        </Button>
      </div>
    </Card>
  )
}

function Instances() {
  const [instances, setInstances] = useState<Instance[]>()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<string>()
  const [message, setMessage] = useState<string>()
  const [query, setQuery] = useState('')

  const load = () =>
    api
      .instances()
      .then(setInstances)
      .catch(() => setInstances([]))
  useEffect(() => {
    void load()
  }, [])

  const login = async (target: string) => {
    setBusy(target)
    setMessage(undefined)
    const res = await api
      .loginInstance(target)
      .catch((e: Error) => ({ ok: false, message: e.message }))
    setBusy(undefined)
    setMessage(res.ok ? undefined : res.message)
    void load()
  }

  const shown = (instances ?? [])
    .filter((i) => !query || `${i.alias} ${i.url}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => Number(b.valid) - Number(a.valid) || a.alias.localeCompare(b.alias))
  const signedIn = instances?.filter((i) => i.valid).length ?? 0

  return (
    <Card className="overflow-hidden">
      <div className="border-line flex items-center gap-2 border-b px-4 py-2.5">
        <label className="border-line-strong focus-within:border-brand flex h-9 flex-1 items-center gap-2 rounded-full border bg-white px-3.5">
          <Search className="text-faint size-3.5" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter instances"
            className="placeholder:text-faint w-full bg-transparent text-[12.5px] outline-none"
          />
        </label>
        {instances ? (
          <span className="text-muted shrink-0 text-[12px]">
            {signedIn} of {instances.length} signed in
          </span>
        ) : null}
      </div>
      <div className="divide-line max-h-[320px] scrollbar-thin divide-y overflow-y-auto">
        {!instances
          ? [0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-3">
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-2.5 w-48" />
                </div>
                <Skeleton className="h-6 w-20 rounded-full" />
              </div>
            ))
          : shown.map((i) => (
              <div key={i.alias} className="flex items-center gap-3 px-4 py-2.5">
                <span
                  className={cn(
                    'size-2 shrink-0 rounded-full',
                    i.valid ? 'bg-ok' : 'bg-line-strong',
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-fg text-[13px] font-medium">
                    {i.alias}
                    {i.current ? (
                      <span className="text-faint ml-1.5 text-[11px] font-normal">current</span>
                    ) : null}
                  </div>
                  <div className="text-faint truncate text-[11.5px]">
                    {i.url.replace('https://', '')}
                    {i.valid ? '' : ' - session expired'}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant={i.valid ? 'ghost' : 'secondary'}
                  disabled={busy === i.url}
                  onClick={() => void login(i.url)}
                >
                  {busy === i.url ? (
                    <Spinner className="size-3.5" />
                  ) : (
                    <KeyRound className="size-3.5" />
                  )}
                  {i.valid ? 'Refresh' : 'Sign in'}
                </Button>
              </div>
            ))}
        {instances && !shown.length ? (
          <div className="text-muted px-4 py-6 text-center text-[12.5px]">
            {instances.length ? 'No instances match.' : 'Not signed in to any instance yet.'}
          </div>
        ) : null}
      </div>
      <form
        className="border-line flex gap-2 border-t px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (url.trim()) void login(url.trim())
        }}
      >
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Add instance, e.g. acme.onevizion.com"
        />
        <Button type="submit" variant="primary" disabled={!url.trim() || Boolean(busy)}>
          Sign in
        </Button>
      </form>
      {message ? (
        <div className="text-danger border-line border-t px-4 py-2.5 text-[12.5px]">{message}</div>
      ) : null}
    </Card>
  )
}

const NEW = '__new__'

function Switch({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      title={label}
      onClick={onChange}
      className={cn(
        'relative h-4 w-7 shrink-0 rounded-full transition-colors',
        on ? 'bg-brand' : 'bg-line-strong',
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 size-3 rounded-full bg-white shadow transition-all',
          on ? 'left-3.5' : 'left-0.5',
        )}
      />
    </button>
  )
}

function Skills() {
  const [skills, setSkills] = useState<SkillInfo[]>()
  const [selected, setSelected] = useState<string>()
  const [draft, setDraft] = useState({ title: '', description: '', content: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()

  const select = (name: string, list = skills ?? []) => {
    const skill = list.find((s) => s.name === name)
    setSelected(name)
    setError(undefined)
    setDraft(
      skill
        ? { title: skill.title, description: skill.description, content: skill.content }
        : { title: '', description: '', content: '' },
    )
  }

  useEffect(() => {
    api.skills().then((s) => {
      setSkills(s)
      if (s[0]) select(s[0].name, s)
    })
  }, [])

  if (!skills)
    return (
      <Card className="p-5">
        <SkeletonText lines={6} />
      </Card>
    )
  const current = skills.find((s) => s.name === selected)
  const creating = selected === NEW
  const dirty = creating
    ? Boolean(draft.title.trim())
    : current
      ? draft.content !== current.content ||
        (!current.builtin &&
          (draft.title !== current.title || draft.description !== current.description))
      : false

  const save = async () => {
    setSaving(true)
    setError(undefined)
    try {
      if (creating) {
        const res = await api.createSkill(draft)
        setSkills(res.skills)
        select(res.name, res.skills)
      } else if (current) {
        const patch = current.builtin ? { content: draft.content } : draft
        const next = await api.updateSkill(current.name, patch)
        setSkills(next)
        select(current.name, next)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!current) return
    if (!current.builtin) {
      const ok = await dialog.confirm({
        title: `Delete "${current.title}"?`,
        body: 'The skill is removed for new runs. This cannot be undone.',
        confirmLabel: 'Delete',
        tone: 'danger',
      })
      if (!ok) return
    }
    const next = await api.deleteSkill(current.name)
    setSkills(next)
    select(next.find((s) => s.name === current.name)?.name ?? next[0]?.name ?? NEW, next)
  }

  const toggle = async (skill: SkillInfo) => {
    setSkills(await api.updateSkill(skill.name, { enabled: !skill.enabled }))
  }

  const editable = creating || (current && !current.builtin)

  return (
    <Card className="grid overflow-hidden md:grid-cols-[220px_1fr]">
      <div className="border-line border-b p-2 md:border-r md:border-b-0">
        {skills.map((s) => (
          <div
            key={s.name}
            className={cn(
              'flex items-start gap-2 rounded-2xl px-3 py-2 transition-colors',
              s.name === selected ? 'bg-brand-soft' : 'hover:bg-raised',
            )}
          >
            <button
              type="button"
              onClick={() => select(s.name)}
              className="min-w-0 flex-1 text-left"
            >
              <div
                className={cn(
                  'flex items-center gap-2 text-[13px] font-medium',
                  !s.enabled && 'text-faint',
                )}
              >
                <span className="truncate">{s.title}</span>
                {s.customized ? (
                  <span className="bg-accent size-1.5 shrink-0 rounded-full" title="Customized" />
                ) : null}
                {!s.builtin ? (
                  <span className="text-faint text-[10.5px] font-normal">yours</span>
                ) : null}
              </div>
              <div className="text-faint mt-0.5 line-clamp-2 text-[11.5px]">{s.description}</div>
            </button>
            <div className="pt-1">
              <Switch
                on={s.enabled}
                label={s.enabled ? 'Used in new runs' : 'Off'}
                onChange={() => void toggle(s)}
              />
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={() => select(NEW)}
          className={cn(
            'text-brand-strong mt-1 flex w-full items-center gap-1.5 rounded-full px-3 py-2 text-[13px] font-medium',
            creating ? 'bg-brand-soft' : 'hover:bg-raised',
          )}
        >
          <Plus className="size-3.5" /> New skill
        </button>
      </div>
      {creating || current ? (
        <div className="flex flex-col gap-3 p-4">
          {editable ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label>Title</Label>
                <Input
                  value={draft.title}
                  onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                  placeholder="e.g. Support case replies"
                />
              </div>
              <div>
                <Label>Description</Label>
                <Input
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  placeholder="One line: what this teaches the agent"
                />
              </div>
            </div>
          ) : null}
          <Textarea
            value={draft.content}
            onChange={(e) => setDraft({ ...draft, content: e.target.value })}
            rows={18}
            placeholder="Instructions in Markdown. They are added to the agent's system prompt."
            className="font-mono text-[12.5px] leading-relaxed"
          />
          {error ? <div className="text-danger text-[12px]">{error}</div> : null}
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              {saving ? <Spinner className="size-3.5" /> : <Save className="size-3.5" />}
              {creating ? 'Create' : 'Save'}
            </Button>
            {current?.builtin && current.customized ? (
              <Button size="sm" variant="ghost" onClick={() => void remove()}>
                <RotateCcw className="size-3.5" /> Reset to default
              </Button>
            ) : null}
            {current && !current.builtin ? (
              <Button size="sm" variant="ghost" onClick={() => void remove()}>
                <Trash2 className="size-3.5" /> Delete
              </Button>
            ) : null}
            <span className="text-faint ml-auto text-[12px]">Applies to new runs</span>
          </div>
        </div>
      ) : null}
    </Card>
  )
}

const EMPTY_SOURCE = { name: '', description: '', location: '' }

function Sources() {
  const [sources, setSources] = useState<SourceInfo[]>()
  const [draft, setDraft] = useState(EMPTY_SOURCE)
  const [editing, setEditing] = useState<string>()
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    api
      .sources()
      .then(setSources)
      .catch(() => setSources([]))
  }, [])

  const act = async (key: string, fn: () => Promise<SourceInfo[]>) => {
    setBusy(key)
    setError(undefined)
    try {
      setSources(await fn())
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(undefined)
    }
  }

  const submit = async () => {
    const ok = editing
      ? await act('save', () =>
          api.updateSource(editing, { description: draft.description, location: draft.location }),
        )
      : await act('save', () => api.addSource(draft))
    if (ok) {
      setDraft(EMPTY_SOURCE)
      setEditing(undefined)
    }
  }

  if (!sources)
    return (
      <Card className="p-5">
        <SkeletonText lines={3} />
      </Card>
    )

  return (
    <Card className="overflow-hidden">
      <div className="divide-line divide-y">
        {sources.map((s) => (
          <div key={s.name} className="flex items-center gap-3 px-4 py-2.5">
            <FolderGit2 className={cn('size-4 shrink-0', s.ready ? 'text-muted' : 'text-danger')} />
            <div className="min-w-0 flex-1">
              <div className="text-fg text-[13px] font-medium">
                {s.name}
                <span className="text-faint ml-1.5 text-[11px] font-normal">
                  {s.kind === 'git' ? 'git' : 'folder'}
                  {s.ready ? '' : ' - missing'}
                </span>
              </div>
              <div className="text-faint truncate text-[11.5px]" title={s.path}>
                {s.description || s.location}
              </div>
            </div>
            {s.kind === 'git' ? (
              <IconButton
                label="Pull latest"
                onClick={() => void act(s.name, () => api.syncSource(s.name))}
              >
                {busy === s.name ? (
                  <Spinner className="size-3.5" />
                ) : (
                  <RefreshCw className="size-3.5" />
                )}
              </IconButton>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(s.name)
                setDraft({ name: s.name, description: s.description, location: s.location })
              }}
            >
              Edit
            </Button>
            <IconButton
              label="Remove source"
              onClick={async () => {
                const ok = await dialog.confirm({
                  title: `Remove ${s.name}?`,
                  body:
                    s.kind === 'git'
                      ? 'The agent stops using it and the local clone is deleted.'
                      : 'The agent stops using it. The folder itself is not touched.',
                  confirmLabel: 'Remove',
                  tone: 'danger',
                })
                if (ok) void act(s.name, () => api.deleteSource(s.name))
              }}
            >
              <Trash2 className="size-3.5" />
            </IconButton>
          </div>
        ))}
        {!sources.length ? (
          <div className="text-muted px-4 py-5 text-center text-[12.5px]">
            No sources yet. Add a code checkout, a docs folder, or a git URL.
          </div>
        ) : null}
      </div>
      <form
        className="border-line grid gap-2 border-t px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div className="text-muted text-[12px] font-medium">
          {editing ? `Edit ${editing}` : 'Add a source'}
        </div>
        <div className="grid gap-2 sm:grid-cols-[160px_1fr]">
          <Input
            value={draft.name}
            disabled={Boolean(editing)}
            onChange={(e) => setDraft({ ...draft, name: e.target.value.toLowerCase() })}
            placeholder="name, e.g. platform"
          />
          <Input
            value={draft.location}
            onChange={(e) => setDraft({ ...draft, location: e.target.value })}
            placeholder="Folder path, or git URL to clone"
          />
        </div>
        <Input
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          placeholder="What is in it, so the agent knows when to look (e.g. platform Java and DDL under db/ddl)"
        />
        <div className="flex items-center gap-2">
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={!draft.name.trim() || !draft.location.trim() || busy === 'save'}
          >
            {busy === 'save' ? <Spinner className="size-3.5" /> : <Plus className="size-3.5" />}
            {editing ? 'Save' : 'Add'}
          </Button>
          {editing ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(undefined)
                setDraft(EMPTY_SOURCE)
              }}
            >
              Cancel
            </Button>
          ) : null}
          {busy === 'save' && /^(https?:|git@|ssh:)/.test(draft.location) ? (
            <span className="text-muted text-[12px]">Cloning...</span>
          ) : null}
        </div>
        {error ? <div className="text-danger text-[12px]">{error}</div> : null}
      </form>
    </Card>
  )
}

export function SettingsPage({ onChange }: { onChange: () => void }) {
  const [user, setUser] = useState<string>()
  useEffect(() => {
    api.status().then((s) => setUser(s.copilot.user))
  }, [])

  return (
    <Page
      title="Settings"
      subtitle={
        <span>Defaults, instances, skills, sources and account. Stored on this machine.</span>
      }
    >
      <div className="divide-line mx-auto max-w-[1040px] divide-y px-6 pb-6">
        <Section title="Preferences" hint="Defaults for new runs.">
          <Preferences onChange={onChange} />
        </Section>
        <Section
          title="Instances"
          hint="OneVizion instances signed in with ov. The agent only reads from them unless you allow changes in a run."
        >
          <Instances />
        </Section>
        <Section
          title="Skills"
          hint="Instructions added to every run. Edit the built-in ones, switch any off, or write your own."
        >
          <Skills />
        </Section>
        <Section
          title="Sources"
          hint="Code and docs the agent can search: a local folder or a git repo it clones for you."
        >
          <Sources />
        </Section>
        <Section title="Account" hint="GitHub Copilot powers the agent.">
          <Card className="flex items-center gap-3 p-5">
            <GithubMark className="size-5" />
            <div className="flex-1 text-[13.5px]">
              {user ? `Signed in as ${user}` : 'Not signed in'}
            </div>
            {user ? (
              <Button
                size="sm"
                variant="danger"
                onClick={async () => {
                  await api.copilotLogout()
                  onChange()
                }}
              >
                <LogOut className="size-3.5" /> Sign out
              </Button>
            ) : null}
          </Card>
        </Section>
      </div>
    </Page>
  )
}
