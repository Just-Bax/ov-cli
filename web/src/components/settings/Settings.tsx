import {
  CaretDown as CaretDownIcon,
  Check as CheckIcon,
  CopySimple as CopyIcon,
  Folder as FolderIcon,
  Key as KeyIcon,
  MagnifyingGlass as MagnifyingGlassIcon,
  Plus as PlusIcon,
  Trash as TrashIcon,
} from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { SkillInfo, Status } from '@shared/types.ts'
import { dialog } from '@/components/common/Dialog'
import { reportError } from '@/components/common/Toasts'
import {
  Button,
  Card,
  Chip,
  IconButton,
  Input,
  Label,
  Page,
  Segmented,
  Skeleton,
  SkeletonText,
  SWITCH_TRACK,
  SwitchKnob,
  Textarea,
} from '@/components/common/ui'
import { DatadogAccountRow, DatadogCard, useDatadog } from '@/components/integrations/Datadog'
import {
  PagerDutyAccountRow,
  PagerDutyCard,
  usePagerDuty,
} from '@/components/integrations/PagerDuty'
import { AccountRow } from '@/components/integrations/parts'
import { PROVIDER_UI } from '@/components/providers'
import { CostSettings } from '@/components/settings/CostSettings'
import { AccessLine, PlatformLabel } from '@/components/settings/AccessLine'
import { ProviderSettings } from '@/components/settings/ProviderSettings'
import { Row } from '@/components/settings/Row'
import {
  AddInstanceForm,
  SignInModal,
  type SignInTarget,
  signInKey,
} from '@/components/signin/SignInModal'
import { api } from '@/lib/api'
import { allowNotifications, notificationsBlocked, notificationsSupported } from '@/lib/attention'
import { cn } from '@/lib/cn'
import { useLoad } from '@/lib/hooks'
import { useInstances } from '@/lib/instances'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'
import { useSettings } from '@/lib/settings'
import { UnsavedGuard, useUnsavedWarning } from '@/lib/unsaved'

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
const NOTIFY_HINT =
  'A desktop notification when a thread needs your answer, finishes or fails while you are looking elsewhere.'
const BLOCKED_HINT =
  'Notifications are blocked for this site. Allow them in the browser site settings, then switch this on.'
const NEW = '__new__'
const EMPTY_DRAFT = { title: '', description: '', content: '' }

function Preferences() {
  const { settings, update } = useSettings()
  const [advanced, setAdvanced] = useState(false)

  const toggleNotify = async () => {
    if (settings.notify) return update({ notify: false })
    if (!notificationsSupported())
      return dialog.alert('No notifications', 'This browser cannot show desktop notifications.')
    if (!(await allowNotifications())) return dialog.alert('Notifications blocked', BLOCKED_HINT)
    await update({ notify: true })
  }

  return (
    <Card className="divide-line divide-y">
      <Row title="Desktop notifications" hint={notificationsBlocked() ? BLOCKED_HINT : NOTIFY_HINT}>
        <Switch
          on={settings.notify && !notificationsBlocked()}
          onChange={() => void toggleNotify()}
          label="Desktop notifications"
        />
      </Row>
      <Row
        title="Tab badge"
        hint="A yellow dot on the browser tab icon, and a count in its title, while threads need you or finished unseen."
      >
        <Switch
          on={settings.tabBadge}
          onChange={() => void update({ tabBadge: !settings.tabBadge })}
          label="Tab badge"
        />
      </Row>
      <div>
        <button
          type="button"
          aria-expanded={advanced}
          onClick={() => setAdvanced((v) => !v)}
          className="text-muted hover:text-fg flex w-full items-center gap-1.5 px-5 py-3 text-[12.5px] font-medium transition-colors"
        >
          Advanced
          <CaretDownIcon className={cn('size-3 transition-transform', advanced && 'rotate-180')} />
        </button>
        {advanced ? (
          <div className="border-line border-t">
            <Row
              title="Step limit"
              hint="How many tool steps a thread may take before it stops. Big investigations need more."
            >
              <Segmented
                label="Step limit"
                value={settings.maxSteps}
                options={(STEP_LIMITS.includes(settings.maxSteps)
                  ? STEP_LIMITS
                  : [...STEP_LIMITS, settings.maxSteps].sort((a, b) => a - b)
                ).map((n) => ({ value: n, label: n }))}
                onChange={(v) => void update({ maxSteps: v })}
              />
            </Row>
          </div>
        ) : null}
      </div>
    </Card>
  )
}

function Instances() {
  const { instances, setInstances, reload } = useInstances()
  const [query, setQuery] = useState('')
  const [target, setTarget] = useState<SignInTarget>()
  const [pending, setPending] = useState<Set<string>>(new Set())

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

  const checkAccess = (alias: string) => {
    setInstances((list) =>
      list?.map((i) =>
        i.alias === alias ? { ...i, access: { ...i.access, checking: true, error: undefined } } : i,
      ),
    )
    api.checkAccess(alias).then(setInstances, (e: unknown) => {
      reportError(e)
      void reload()
    })
  }

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
      <div className="divide-line max-h-[420px] scrollbar-thin divide-y overflow-y-auto">
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
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="text-fg min-w-0 truncate text-[13px] font-medium">
                        {i.host}
                      </span>
                      {i.tenant ? <Chip tone="brand">{i.tenant}</Chip> : null}
                      {i.mode === 'token' ? <Chip tone="neutral">API token</Chip> : null}
                      <PlatformLabel instance={i} />
                    </div>
                    <AccessLine instance={i} onCheck={() => checkAccess(i.alias)} />
                  </div>
                  <Chip tone={i.valid ? 'ok' : 'neutral'}>{i.valid ? 'Signed in' : 'Expired'}</Chip>
                  <Button
                    size="sm"
                    variant={i.valid ? 'ghost' : 'secondary'}
                    busy={busy}
                    onClick={() => setTarget(row)}
                  >
                    <KeyIcon className="size-3.5" />
                    {busy ? 'Signing in' : i.valid ? 'Refresh' : 'Sign in'}
                  </Button>
                  <IconButton
                    label="Remove instance"
                    className="hover:text-danger hover:bg-danger-soft"
                    onClick={async () => {
                      const name = i.tenant ? `${i.host} (${i.tenant})` : i.host
                      const ok = await dialog.confirm({
                        title: `Remove ${name}?`,
                        body: 'Signs out and forgets it on this computer. Threads, maps and Datadog matches are kept; sign in again to use it.',
                        confirmLabel: 'Remove',
                        tone: 'danger',
                      })
                      if (!ok) return

                      setInstances((list) => list?.filter((x) => x.alias !== i.alias))
                      try {
                        setInstances(await api.removeInstance(i.alias))
                      } catch (e) {
                        void reload()
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
          void reload()
        }}
      />
    </Card>
  )
}

function Switch({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      title={label}
      onClick={onChange}
      className={cn(SWITCH_TRACK, on ? 'bg-brand' : 'bg-line-strong')}
    >
      <SwitchKnob on={on} />
    </button>
  )
}

function Skills() {
  const [skills, setSkills] = useState<SkillInfo[]>()
  const [selected, setSelected] = useState<string>()
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()

  const select = (name: string, list = skills ?? []) => {
    const skill = list.find((s) => s.name === name)
    setSelected(name)
    setError(undefined)
    setDraft(
      skill
        ? { title: skill.title, description: skill.description, content: skill.content }
        : EMPTY_DRAFT,
    )
  }

  useEffect(() => {
    api
      .skills()
      .then((s) => {
        setSkills(s)
        if (s[0]) select(s[0].name, s)
      })
      .catch(reportError)
  }, [])

  if (!skills)
    return (
      <Card className="p-5">
        <SkeletonText lines={6} />
      </Card>
    )

  const current = skills.find((s) => s.name === selected)
  const creating = selected === NEW
  const bundled = current?.source === 'bundled'
  const editable = creating || (current !== undefined && !bundled)

  const dirty = creating
    ? Boolean(draft.title.trim())
    : current && !bundled
      ? draft.content !== current.content ||
        draft.title !== current.title ||
        draft.description !== current.description
      : false

  const show = (name: string, list: SkillInfo[]) => {
    setSkills(list)
    select(name, list)
  }

  const withSaving = async (work: () => Promise<void>) => {
    setSaving(true)
    setError(undefined)
    try {
      await work()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const save = () =>
    withSaving(async () => {
      if (creating) {
        const res = await api.createSkill(draft)
        return show(res.name, res.skills)
      }
      if (current) show(current.name, await api.updateSkill(current.name, draft))
    })

  const clone = (skill: SkillInfo) =>
    withSaving(async () => {
      const res = await api.cloneSkill(skill.name)
      show(res.name, res.skills)
    })

  const remove = async (skill: SkillInfo) => {
    const ok = await dialog.confirm({
      title: `Delete "${skill.title}"?`,
      body: 'The skill is removed for new threads. This cannot be undone.',
      confirmLabel: 'Delete',
      tone: 'danger',
    })
    if (!ok) return

    const next = await api.deleteSkill(skill.name)
    show(next[0]?.name ?? NEW, next)
  }

  const toggle = async (skill: SkillInfo) => {
    setSkills(await api.updateSkill(skill.name, { enabled: !skill.enabled }))
  }

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
                <span className="text-faint shrink-0 text-[11px] font-normal">
                  {s.core ? 'always' : s.source}
                </span>
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
                {current ? (
                  <Chip tone={bundled ? 'neutral' : 'brand'}>{bundled ? 'Bundled' : 'Custom'}</Chip>
                ) : null}
                {current?.core ? <Chip tone="ok">Always loaded</Chip> : null}
              </div>
            </div>
            {current ? (
              <label className="text-muted flex shrink-0 cursor-pointer items-center gap-2.5 text-[12.5px]">
                {current.enabled ? 'On for new threads' : 'Off'}
                <Switch
                  on={current.enabled}
                  label={current.enabled ? 'Turn off' : 'Turn on'}
                  onChange={() => void toggle(current).catch(reportError)}
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
            readOnly={!editable}
            placeholder="Instructions in Markdown. They are added to the agent's system prompt."
            fill
            className="flex-1 font-mono text-[12.5px] leading-relaxed"
          />
          {error ? <div className="text-danger text-[12px]">{error}</div> : null}
          <div className="flex items-center gap-2">
            {current && bundled ? (
              <Button
                variant="primary"
                size="sm"
                busy={saving}
                disabled={saving}
                onClick={() => void clone(current)}
              >
                <CopyIcon className="size-3.5" />
                Clone to edit
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                busy={saving}
                disabled={!dirty || saving}
                onClick={() => void save()}
              >
                <CheckIcon className="size-3.5" />
                {creating ? 'Create' : 'Save'}
              </Button>
            )}
            {current && !bundled ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void remove(current).catch(reportError)}
              >
                <TrashIcon className="size-3.5" /> Delete
              </Button>
            ) : null}
            <span className="text-faint ml-auto text-[12px]">
              {bundled ? 'Bundled skills are read-only' : 'Applies to new threads'}
            </span>
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
        <Button
          variant="primary"
          size="sm"
          busy={saving}
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          <CheckIcon className="size-3.5" /> Save
        </Button>
        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    </Card>
  )
}

function Profile() {
  const { settings, update } = useSettings()
  const [name, setName] = useState(settings.fullName)
  const [instructions, setInstructions] = useState(settings.instructions)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()

  useEffect(() => setName(settings.fullName), [settings.fullName])
  useEffect(() => setInstructions(settings.instructions), [settings.instructions])

  const dirty = name.trim() !== settings.fullName || instructions !== settings.instructions
  useUnsavedWarning(dirty)

  const save = async () => {
    setSaving(true)
    setError(undefined)
    try {
      await update({ fullName: name.trim(), instructions })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="space-y-4 p-5">
      <div>
        <Label>Full name</Label>
        <Input
          aria-label="Full name"
          className="w-[320px]"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
        />
      </div>
      <div>
        <Label>Instructions</Label>
        <div className="text-muted mb-2 text-[12px] leading-relaxed">
          The agent keeps these in mind in every thread: how you like answers, rules for your work,
          anything it should know about you.
        </div>
        <Textarea
          aria-label="Instructions"
          rows={6}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder={
            'e.g. Keep replies short and plain. Only my tasks count, not the whole team.'
          }
        />
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          busy={saving}
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          <CheckIcon className="size-3.5" /> Save
        </Button>
        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    </Card>
  )
}

function ProviderAccounts({ status, onChange }: { status?: Status; onChange: () => void }) {
  const { providers } = useSettings()

  return providers.map((provider) => {
    const ui = PROVIDER_UI[provider.id]
    const { AccountAction } = ui
    return (
      <AccountRow
        key={provider.id}
        badge={ui.accountBadge}
        title={PROVIDER_BRANDS[provider.id].name}
        detail={ui.accountDetail(provider.account, status?.provider === provider.id)}
        action={
          AccountAction ? <AccountAction account={provider.account} onChange={onChange} /> : null
        }
      />
    )
  })
}

export function SettingsPage({ onChange }: { onChange: () => void }) {
  const { settings } = useSettings()
  const { value: status, reload } = useLoad(api.status, [])
  const datadog = useDatadog()
  const pd = usePagerDuty()

  const changed = () => {
    reload()
    onChange()
  }

  return (
    <Page
      title="Settings"
      subtitle={
        <span>
          Profile, provider, cost, preferences, instances, integrations, skills, workspace and
          accounts. Stored on this machine.
        </span>
      }
    >
      <div className="divide-line mx-auto max-w-[1040px] divide-y px-6 pb-6">
        <Section
          title="Profile"
          hint="Who you are and how you like to work. Added to every new turn, in every thread."
        >
          <Profile />
        </Section>
        <Section
          title="Provider"
          hint="Who runs the agent, its account and its models. Saved as you change them."
        >
          <ProviderSettings onChange={changed} />
        </Section>
        <Section
          title="Cost"
          hint="What the agent used on the provider above; pick another one to compare. Each thread shows its own total in its header."
        >
          <CostSettings key={settings.provider} />
        </Section>
        <Section
          title="Preferences"
          hint="What you see and how far threads go. Saved as you change them."
        >
          <Preferences />
        </Section>
        <Section
          title="Instances"
          hint="OneVizion instances signed in with ov, and what your account can use on each. The agent picks its sources from that, and only reads unless you allow changes in a thread."
        >
          <Instances />
        </Section>
        <Section
          title="Integrations"
          hint="Outside services the agent can read from, and the Instance health page draws on."
        >
          <div className="space-y-4">
            <DatadogCard status={datadog.status} setStatus={datadog.setStatus} />
            <PagerDutyCard status={pd.status} setStatus={pd.setStatus} />
          </div>
        </Section>
        <Section
          title="Skills"
          hint="Instructions added to every thread. Bundled ones are read-only: switch them off or clone one to edit it. Or write your own."
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
            <ProviderAccounts status={status} onChange={changed} />
            <DatadogAccountRow status={datadog.status} setStatus={datadog.setStatus} />
            <PagerDutyAccountRow status={pd.status} setStatus={pd.setStatus} />
          </Card>
        </Section>
      </div>
    </Page>
  )
}
