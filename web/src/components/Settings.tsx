import {
  ArrowRightStartOnRectangleIcon,
  ArrowUturnLeftIcon,
  CheckIcon,
  FolderIcon,
  KeyIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  TrashIcon,
} from '@heroicons/react/24/outline'
import { useEffect, useState } from 'react'
import type { Instance, SkillInfo } from '@shared/types.ts'
import {
  AccountRow,
  DatadogAccountRow,
  DatadogCard,
  useDatadog,
} from '@/components/datadog/Datadog'
import { dialog } from '@/components/Dialog'
import { PagerDutyAccountRow, PagerDutyCard, usePagerDuty } from '@/components/pagerduty/PagerDuty'
import {
  AddInstanceForm,
  SignInModal,
  type SignInTarget,
  signInKey,
} from '@/components/SignInModal'
import { useModels } from '@/components/ModelPicker'
import {
  Button,
  Card,
  Chip,
  GithubMark,
  IconBadge,
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
import { UnsavedGuard, useUnsavedWarning } from '@/lib/unsaved'
import { go } from '@/lib/route'
import { cn } from '@/lib/cn'
import { href } from '@/lib/route'
import { useSettings } from '@/lib/settings'
import { reportError } from '@/components/Toasts'

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
    <section className="grid gap-6 py-6 xl:grid-cols-[200px_1fr]">
      <div>
        <div className="text-fg text-[13.5px] font-semibold">{title}</div>
        {hint ? <div className="text-muted mt-1 text-[12px] leading-relaxed">{hint}</div> : null}
      </div>
      <div>{children}</div>
    </section>
  )
}

const STEP_LIMITS = [40, 80, 150, 300]

function Row({
  title,
  hint,
  children,
}: {
  title: string
  hint: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
      <div className="min-w-[240px] flex-1">
        <div className="text-fg text-[13.5px] font-medium">{title}</div>
        <div className="text-muted mt-0.5 text-[12px] leading-relaxed">{hint}</div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Segmented({
  value,
  options,
  onChange,
}: {
  value: number
  options: number[]
  onChange: (v: number) => void
}) {
  return (
    <div className="bg-raised flex rounded-full p-1">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          onClick={() => onChange(o)}
          className={cn(
            'h-7 min-w-11 rounded-full px-3 text-[12.5px] font-medium transition-colors',
            o === value ? 'text-fg bg-white shadow-sm' : 'text-muted hover:text-fg',
          )}
        >
          {o}
        </button>
      ))}
    </div>
  )
}

function Preferences() {
  const { settings, update } = useSettings()
  const models = useModels()
  const [notice, setNotice] = useState<string>()

  const toggleNotify = async () => {
    setNotice(undefined)
    if (settings.notify) return void update({ notify: false })
    if (!('Notification' in window))
      return setNotice('This browser does not support notifications.')

    const permission = await Notification.requestPermission()
    if (permission !== 'granted')
      return setNotice('Notifications are blocked for this page. Allow them in the browser first.')

    await update({ notify: true })
  }

  const testNotify = () => {
    setNotice(undefined)
    if (Notification.permission !== 'granted')
      return setNotice('Notifications are blocked for this page. Allow them in the browser first.')

    new Notification('Run needs you', {
      body: 'This is how OV Agent notifications look.',
      icon: '/favicon-32.png',
    })
    setNotice(
      'Sent. If nothing appeared, check Windows notification settings and Focus Assist for this browser.',
    )
  }

  return (
    <Card className="divide-line divide-y">
      <Row title="Main model" hint="Used for new runs. You can switch it per run in the chat.">
        <Select
          className="w-[260px]"
          value={settings.defaultModel}
          onChange={(v) => void update({ defaultModel: v })}
          placeholder={models.length ? 'Pick a model' : 'Loading models...'}
          options={models.map((m) => ({
            value: m.id,
            label: m.name,
            hint: m.premium ? `x${m.premium}` : m.vendor,
          }))}
        />
      </Row>
      <Row
        title="Fast model"
        hint="Used for small chores such as naming runs. A quick, cheap model fits, such as Haiku."
      >
        <Select
          className="w-[260px]"
          value={settings.fastModel}
          onChange={(v) => void update({ fastModel: v })}
          placeholder={models.length ? 'Off' : 'Loading models...'}
          options={[
            { value: '', label: 'Off', hint: 'runs keep their first line' },
            ...models.map((m) => ({
              value: m.id,
              label: m.name,
              hint: m.premium ? `x${m.premium}` : m.vendor,
            })),
          ]}
        />
      </Row>
      <Row
        title="Step limit"
        hint="How many tool steps a run may take before it stops. Big investigations need more."
      >
        <Segmented
          value={settings.maxSteps}
          options={
            STEP_LIMITS.includes(settings.maxSteps)
              ? STEP_LIMITS
              : [...STEP_LIMITS, settings.maxSteps].sort((a, b) => a - b)
          }
          onChange={(v) => void update({ maxSteps: v })}
        />
      </Row>
      <Row
        title="Desktop notifications"
        hint={
          notice ??
          'Notify me when a run finishes, fails or needs me. In this window you get a toast instead, unless you are already looking at that run.'
        }
      >
        <div className="flex items-center gap-2">
          {settings.notify && (
            <Button size="sm" variant="ghost" onClick={testNotify}>
              Test
            </Button>
          )}
          <Switch
            on={settings.notify}
            onChange={() => void toggleNotify()}
            label="Desktop notifications"
          />
        </div>
      </Row>
      <Row
        title="Show time saved"
        hint="The agent's estimate of how long the work would take by hand."
      >
        <Switch
          on={settings.showTimeSaved}
          onChange={() => void update({ showTimeSaved: !settings.showTimeSaved })}
          label="Show time saved"
        />
      </Row>
      <Row
        title="Expand tool calls"
        hint="Open the API calls and SQL of each step instead of a summary."
      >
        <Switch
          on={settings.expandTools}
          onChange={() => void update({ expandTools: !settings.expandTools })}
          label="Expand tool calls"
        />
      </Row>
    </Card>
  )
}

function Instances() {
  const [instances, setInstances] = useState<Instance[]>()
  const [query, setQuery] = useState('')
  const [target, setTarget] = useState<SignInTarget>()
  const [pending, setPending] = useState<Set<string>>(new Set())

  const load = () =>
    api
      .instances()
      .then(setInstances)
      .catch((e: Error) => {
        setInstances([])
        reportError(e)
      })

  useEffect(() => {
    void load()
  }, [])

  const mark = (t: SignInTarget, on: boolean) =>
    setPending((p) => {
      const next = new Set(p)
      if (on) next.add(signInKey(t))
      else next.delete(signInKey(t))
      return next
    })

  const shown = (instances ?? [])
    .filter(
      (i) => !query || `${i.host} ${i.tenant ?? ''}`.toLowerCase().includes(query.toLowerCase()),
    )
    .sort(
      (a, b) =>
        Number(b.valid) - Number(a.valid) ||
        a.host.localeCompare(b.host) ||
        (a.tenant ?? '').localeCompare(b.tenant ?? ''),
    )
  const signedIn = instances?.filter((i) => i.valid).length ?? 0

  return (
    <Card className="overflow-hidden">
      <div className="border-line flex items-center gap-2 border-b px-5 py-2.5">
        <label className="border-line-strong focus-within:border-brand flex h-9 flex-1 items-center gap-2 rounded-full border bg-white px-3.5">
          <MagnifyingGlassIcon className="text-faint size-3.5" />
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
          : shown.map((i) => {
              const row: SignInTarget = {
                url: i.url,
                host: i.host,
                tenant: i.tenant ?? undefined,
                mode: i.mode === 'token' ? 'token' : 'browser',
              }
              const busy = pending.has(signInKey(row))

              return (
                <div key={i.alias} className="flex items-center gap-2.5 px-5 py-2.5">
                  <span className="text-fg min-w-0 truncate text-[13px] font-medium">{i.host}</span>
                  {i.tenant ? <Chip tone="brand">{i.tenant}</Chip> : null}
                  {i.mode === 'token' ? <Chip tone="neutral">API token</Chip> : null}
                  <div className="flex-1" />
                  <Chip tone={i.valid ? 'ok' : 'neutral'}>{i.valid ? 'Signed in' : 'Expired'}</Chip>
                  <Button
                    size="sm"
                    variant={i.valid ? 'ghost' : 'secondary'}
                    onClick={() => setTarget(row)}
                  >
                    {busy ? <Spinner className="size-3.5" /> : <KeyIcon className="size-3.5" />}
                    {busy ? 'Signing in' : i.valid ? 'Refresh' : 'Sign in'}
                  </Button>
                  <IconButton
                    label="Remove instance"
                    className="hover:text-danger hover:bg-danger-soft"
                    onClick={async () => {
                      const name = i.tenant ? `${i.host} (${i.tenant})` : i.host
                      const ok = await dialog.confirm({
                        title: `Remove ${name}?`,
                        body: 'Signs out and forgets it on this computer. Runs, maps and Datadog matches are kept; sign in again to use it.',
                        confirmLabel: 'Remove',
                        tone: 'danger',
                      })
                      if (!ok) return

                      try {
                        setInstances(await api.removeInstance(i.alias))
                      } catch (e) {
                        await dialog.alert('Could not remove it', (e as Error).message)
                      }
                    }}
                  >
                    <TrashIcon className="size-3.5" />
                  </IconButton>
                </div>
              )
            })}
        {instances && !shown.length ? (
          <div className="text-muted px-4 py-6 text-center text-[12.5px]">
            {instances.length ? 'No instances match.' : 'Not signed in to any instance yet.'}
          </div>
        ) : null}
      </div>
      <AddInstanceForm className="border-line border-t px-5 py-3" onSubmit={setTarget} />
      <SignInModal
        target={target}
        pending={Boolean(target && pending.has(signInKey(target)))}
        onClose={() => setTarget(undefined)}
        onStart={(t) => mark(t, true)}
        onFinished={(t) => {
          mark(t, false)
          void load()
        }}
      />
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
    <Card className="grid overflow-hidden md:grid-cols-[230px_1fr]">
      <div className="border-line scrollbar-thin border-b p-2 md:max-h-[560px] md:overflow-y-auto md:border-r md:border-b-0">
        <div className="space-y-0.5">
          {skills.map((s) => {
            const on = s.name === selected
            return (
              <button
                key={s.name}
                type="button"
                onClick={() => select(s.name)}
                className={cn(
                  'flex h-9 w-full items-center gap-2.5 rounded-full px-3.5 text-left text-[13px] font-medium transition-colors',
                  on
                    ? 'bg-brand-soft text-brand-strong'
                    : s.enabled
                      ? 'text-text hover:bg-canvas hover:text-brand-strong'
                      : 'text-faint hover:bg-canvas',
                )}
              >
                <span
                  className={cn(
                    'size-1.5 shrink-0 rounded-full',
                    s.enabled ? 'bg-ok' : 'bg-line-strong',
                  )}
                />
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                {s.core ? (
                  <span className="text-faint shrink-0 text-[11px] font-normal">always</span>
                ) : !s.builtin ? (
                  <span className="text-faint shrink-0 text-[11px] font-normal">yours</span>
                ) : s.customized ? (
                  <span className="text-faint shrink-0 text-[11px] font-normal">edited</span>
                ) : null}
              </button>
            )
          })}
          <button
            type="button"
            onClick={() => select(NEW)}
            className={cn(
              'text-brand-strong flex h-9 w-full items-center gap-2.5 rounded-full px-3.5 text-[13px] font-medium transition-colors',
              creating ? 'bg-brand-soft' : 'hover:bg-canvas',
            )}
          >
            <PlusIcon className="size-3.5" /> New skill
          </button>
        </div>
      </div>
      <UnsavedGuard dirty={dirty} />
      {creating || current ? (
        <div className="flex h-[560px] flex-col gap-3 p-4">
          <div className="flex items-center gap-3 px-1">
            <div className="min-w-0 flex-1">
              <div className="text-fg flex flex-wrap items-center gap-2 text-[14px] font-semibold">
                <span className="truncate">{creating ? 'New skill' : current?.title}</span>
                {current?.builtin ? <Chip>Built-in</Chip> : null}
                {current?.core ? <Chip tone="ok">Always loaded</Chip> : null}
                {current?.customized ? <Chip tone="brand">Edited</Chip> : null}
              </div>
            </div>
            {current ? (
              <label className="text-muted flex shrink-0 cursor-pointer items-center gap-2.5 text-[12.5px]">
                {current.enabled ? 'On for new runs' : 'Off'}
                <Switch
                  on={current.enabled}
                  label={current.enabled ? 'Turn off' : 'Turn on'}
                  onChange={() => void toggle(current)}
                />
              </label>
            ) : null}
          </div>
          {!editable && current ? (
            <div className="bg-raised text-text rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-relaxed">
              {current.description || 'No description.'}
            </div>
          ) : null}
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
            placeholder="Instructions in Markdown. They are added to the agent's system prompt."
            fill
            className="flex-1 font-mono text-[12.5px] leading-relaxed"
          />
          {error ? <div className="text-danger text-[12px]">{error}</div> : null}
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              {saving ? <Spinner className="size-3.5" /> : <CheckIcon className="size-3.5" />}
              {creating ? 'Create' : 'Save'}
            </Button>
            {current?.builtin && current.customized ? (
              <Button size="sm" variant="ghost" onClick={() => void remove()}>
                <ArrowUturnLeftIcon className="size-3.5" /> Reset to default
              </Button>
            ) : null}
            {current && !current.builtin ? (
              <Button size="sm" variant="ghost" onClick={() => void remove()}>
                <TrashIcon className="size-3.5" /> Delete
              </Button>
            ) : null}
            <span className="text-faint ml-auto text-[12px]">Applies to new runs</span>
          </div>
        </div>
      ) : null}
    </Card>
  )
}

function Workspace() {
  const { settings, update } = useSettings()
  const [folder, setFolder] = useState(settings.workspace)
  const [notes, setNotes] = useState(settings.workspaceNotes)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()

  useEffect(() => setFolder(settings.workspace), [settings.workspace])
  useEffect(() => setNotes(settings.workspaceNotes), [settings.workspaceNotes])

  const dirty = folder.trim() !== settings.workspace || notes !== settings.workspaceNotes
  useUnsavedWarning(dirty)

  const save = async () => {
    setSaving(true)
    setError(undefined)
    try {
      await update({ workspace: folder.trim(), workspaceNotes: notes })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="space-y-3 p-5">
      <div className="flex items-center gap-2">
        <FolderIcon className="text-muted size-4 shrink-0" />
        <Input
          className="flex-1 font-mono text-[12.5px]"
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          placeholder="Folder with your code, e.g. C:\\Projects\\OneVizion"
          spellCheck={false}
        />
      </div>
      <Textarea
        rows={4}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder={
          'Notes for the agent, e.g.\nov/ is the platform repo, modules/ holds Vizion Hub modules (clone new ones there).\nRun Java tests with mvn -q test -pl <module>.'
        }
      />
      <div className="flex items-center gap-2">
        <Button variant="primary" size="sm" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? <Spinner className="size-3.5" /> : <CheckIcon className="size-3.5" />} Save
        </Button>
        {settings.workspace ? (
          <a
            href={href({ page: 'workspace' })}
            className="text-brand-strong text-[12.5px] font-medium hover:underline"
          >
            Open the workspace
          </a>
        ) : null}
        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    </Card>
  )
}

export function SettingsPage({ onChange }: { onChange: () => void }) {
  const [user, setUser] = useState<string>()
  const datadog = useDatadog()
  const pd = usePagerDuty()

  useEffect(() => {
    api.status().then((s) => setUser(s.copilot.user))
  }, [])

  return (
    <Page
      title="Settings"
      subtitle={
        <span>
          Defaults, instances, workspace, integrations, skills and accounts. Stored on this machine.
        </span>
      }
    >
      <div className="divide-line mx-auto max-w-[1040px] divide-y px-6 pb-6">
        <Section
          title="Preferences"
          hint="How runs start and what you see. Saved as you change them."
        >
          <Preferences />
        </Section>
        <Section
          title="Instances"
          hint="OneVizion instances signed in with ov. The agent only reads from them unless you allow changes in a run."
        >
          <Instances />
        </Section>
        <Section
          title="Integrations"
          hint="Outside services the agent can read from, and the Health page draws on."
        >
          <div className="space-y-4">
            <DatadogCard status={datadog.status} setStatus={datadog.setStatus} />
            <PagerDutyCard status={pd.status} setStatus={pd.setStatus} />
          </div>
        </Section>
        <Section
          title="Skills"
          hint="Instructions added to every run. Edit the built-in ones, switch any off, or write your own."
        >
          <Skills />
        </Section>
        <Section
          title="Workspace"
          hint="One folder with your code. The agent reads, edits and runs commands only inside it; deleting files, git push and the like wait for your approval."
        >
          <Workspace />
        </Section>
        <Section title="Accounts" hint="Services this computer is signed in to.">
          <Card className="divide-line divide-y overflow-hidden">
            <AccountRow
              badge={
                <IconBadge tone="neutral">
                  <GithubMark className="size-5" />
                </IconBadge>
              }
              title="GitHub Copilot"
              detail={user ? `Signed in as ${user}. Runs the agent.` : 'Not signed in'}
              action={
                user ? (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      await api.copilotLogout()
                      go({ page: 'home' })
                      onChange()
                    }}
                  >
                    <ArrowRightStartOnRectangleIcon className="size-3.5" /> Sign out
                  </Button>
                ) : null
              }
            />
            <DatadogAccountRow status={datadog.status} setStatus={datadog.setStatus} />
            <PagerDutyAccountRow status={pd.status} setStatus={pd.setStatus} />
          </Card>
        </Section>
      </div>
    </Page>
  )
}
