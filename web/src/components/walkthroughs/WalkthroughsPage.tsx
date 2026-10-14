import { PencilSimple, Play, Plus, TestTube, Trash, X } from '@phosphor-icons/react'
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { WalkRun, WalkStep, WalkStepStatus, Walkthrough } from '@shared/types.ts'
import { dialog } from '@/components/common/Dialog'
import { reportError } from '@/components/common/Toasts'
import {
  type BadgeTone,
  Button,
  EmptyState,
  IconBadge,
  Page,
  Select,
  Skeleton,
  Spinner,
  Textarea,
} from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useInstances } from '@/lib/instances'
import { useLayer } from '@/lib/layers'
import { timeAgo } from '@/lib/time'

const INSTANCE_KEY = 'ov-agent.walkthrough-instance'
const EDITOR_WIDTH = 'min(480px, 100vw)'
const RUN_WIDTH = 'min(560px, 100vw)'
const RECENT_LIMIT = 8

const WORKING: WalkStepStatus[] = ['pending', 'running']

const STATUS_TONE: Record<WalkStepStatus, string> = {
  pending: 'bg-raised text-muted',
  running: 'bg-brand-soft text-brand-strong',
  passed: 'bg-ok-soft text-ok',
  failed: 'bg-danger-soft text-danger',
  blocked: 'bg-warn-soft text-warn',
  error: 'bg-danger-soft text-danger',
  stopped: 'bg-raised text-muted',
}

const STATUS_LABEL: Record<WalkStepStatus, string> = {
  pending: 'Waiting',
  running: 'Running',
  passed: 'Passed',
  failed: 'Failed',
  blocked: 'Blocked',
  error: 'Error',
  stopped: 'Stopped',
}

const BAR_TONE: Record<WalkStepStatus, string> = {
  pending: 'bg-brand',
  running: 'bg-brand',
  passed: 'bg-ok',
  failed: 'bg-danger',
  blocked: 'bg-warn',
  error: 'bg-danger',
  stopped: 'bg-muted',
}

const BADGE_TONE: Record<WalkStepStatus, BadgeTone> = {
  pending: 'brand',
  running: 'brand',
  passed: 'ok',
  failed: 'danger',
  blocked: 'warn',
  error: 'danger',
  stopped: 'neutral',
}

type Draft = { instance: string; title: string; goal: string; steps: string }

type Counts = { total: number; done: number; passed: number; current?: WalkStep }

function toLines(steps: string[]): string {
  return steps.join('\n')
}

function fromDraft(draft: Draft) {
  const steps = draft.steps
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  return { instance: draft.instance, title: draft.title.trim(), goal: draft.goal.trim(), steps }
}

function counts(run: WalkRun): Counts {
  return {
    total: run.steps.length,
    done: run.steps.filter((s) => !WORKING.includes(s.status)).length,
    passed: run.steps.filter((s) => s.status === 'passed').length,
    current: run.steps.find((s) => s.status === 'running'),
  }
}

function useWalkthroughs() {
  const [saved, setSaved] = useState<Walkthrough[]>()
  const [runs, setRuns] = useState<WalkRun[]>([])
  const sources = useRef(new Map<string, EventSource>())

  const reload = useCallback(
    () =>
      api.walkthroughs().then(({ walkthroughs, runs }) => {
        setSaved(walkthroughs)
        setRuns(runs)
      }, reportError),
    [],
  )

  useEffect(() => void reload(), [reload])

  const upsertRun = useCallback((run: WalkRun) => {
    setRuns((list) => {
      const at = list.findIndex((r) => r.id === run.id)
      if (at < 0) return [run, ...list]
      const next = list.slice()
      next[at] = run
      return next
    })
  }, [])

  useEffect(() => {
    const live = sources.current
    for (const run of runs) {
      if (!WORKING.includes(run.status) || live.has(run.id)) continue

      const source = new EventSource(api.walkRunEventsUrl(run.id))
      live.set(run.id, source)
      source.onmessage = (e) => {
        const latest = JSON.parse(e.data) as WalkRun
        upsertRun(latest)
        if (WORKING.includes(latest.status)) return
        source.close()
        live.delete(run.id)
      }
      source.onerror = () => {
        source.close()
        live.delete(run.id)
      }
    }
  }, [runs, upsertRun])

  useEffect(() => {
    const live = sources.current
    return () => {
      for (const source of live.values()) source.close()
      live.clear()
    }
  }, [])

  return { saved, runs, reload, upsertRun }
}

export function WalkthroughsPage() {
  const { instances } = useInstances()
  const signedIn = useMemo(() => (instances ?? []).filter((i) => i.valid), [instances])
  const [instance, setInstance] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const { saved, runs, reload, upsertRun } = useWalkthroughs()
  const [editing, setEditing] = useState<{ walkthrough?: Walkthrough }>()
  const [openRunId, setOpenRunId] = useState<string>()

  useEffect(() => {
    if (!instance && signedIn.length) setInstance(signedIn[0].host)
  }, [signedIn, instance])

  useEffect(() => {
    if (instance) localStorage.setItem(INSTANCE_KEY, instance)
  }, [instance])

  const latest = (id: string) => runs.find((r) => r.walkthroughId === id)
  const openRun = runs.find((r) => r.id === openRunId)

  const run = async (w: Walkthrough) => {
    try {
      upsertRun(await api.startWalkRun({ walkthroughId: w.id }))
    } catch (e) {
      reportError(e as Error)
    }
  }

  const remove = async (w: Walkthrough) => {
    const ok = await dialog.confirm({
      title: `Delete "${w.title}"?`,
      body: 'Its runs and screenshots are removed too.',
      confirmLabel: 'Delete',
      tone: 'danger',
    })
    if (!ok) return

    await api.deleteWalkthrough(w.id).catch(reportError)
    await reload()
  }

  const recent = runs.filter(
    (r) => !r.walkthroughId || !saved?.some((w) => w.id === r.walkthroughId),
  )

  const actions = (
    <>
      <div className="w-[220px]">
        <Select
          value={instance}
          onChange={setInstance}
          placeholder={instances ? 'No signed-in instance' : 'Loading...'}
          options={signedIn.map((i) => ({ value: i.host, label: i.host }))}
        />
      </div>
      <Button variant="primary" disabled={!instance} onClick={() => setEditing({})}>
        <Plus className="size-4" weight="bold" /> New walkthrough
      </Button>
    </>
  )

  return (
    <Page
      title="Walkthroughs"
      subtitle="Browser tests a real user would run on an instance, checked by the fast model at every step."
      actions={actions}
    >
      <div className="mx-auto max-w-[1200px] p-6">
        {!saved ? (
          <Grid>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-44 rounded-2xl" />
            ))}
          </Grid>
        ) : saved.length ? (
          <>
            <Grid>
              {saved.map((w) => (
                <WalkCard
                  key={w.id}
                  walkthrough={w}
                  run={latest(w.id)}
                  onRun={() => void run(w)}
                  onEdit={() => setEditing({ walkthrough: w })}
                  onDelete={() => void remove(w)}
                  onOpen={(r) => setOpenRunId(r.id)}
                />
              ))}
            </Grid>
            {recent.length ? <Recent runs={recent} onOpen={setOpenRunId} /> : null}
          </>
        ) : (
          <EmptyState
            icon={TestTube}
            title="No walkthroughs yet"
            action={
              <Button variant="primary" disabled={!instance} onClick={() => setEditing({})}>
                <Plus className="size-4" weight="bold" /> New walkthrough
              </Button>
            }
          >
            Describe a test a real user would run, let the agent draft the steps, then run it on an
            instance.
          </EmptyState>
        )}
      </div>

      {editing ? (
        <EditorPanel
          instance={instance}
          walkthrough={editing.walkthrough}
          onClose={() => setEditing(undefined)}
          onSaved={reload}
          onRun={(r) => {
            upsertRun(r)
            setOpenRunId(r.id)
          }}
        />
      ) : null}
      {openRun ? (
        <RunPanel
          run={openRun}
          onClose={() => setOpenRunId(undefined)}
          onStop={() => void api.stopWalkRun(openRun.id).catch(reportError)}
        />
      ) : null}
    </Page>
  )
}

function Grid({ children }: { children: ReactNode }) {
  return (
    <div className="grid [grid-template-columns:repeat(auto-fill,minmax(300px,1fr))] gap-4">
      {children}
    </div>
  )
}

function WalkCard({
  walkthrough,
  run,
  onRun,
  onEdit,
  onDelete,
  onOpen,
}: {
  walkthrough: Walkthrough
  run?: WalkRun
  onRun: () => void
  onEdit: () => void
  onDelete: () => void
  onOpen: (run: WalkRun) => void
}) {
  const working = run ? WORKING.includes(run.status) : false
  const steps = walkthrough.steps.length

  return (
    <article className="group/card border-line-strong/70 hover:border-line-strong flex flex-col gap-3 rounded-2xl border bg-white p-4 transition-colors">
      <div className="flex items-start gap-3">
        <IconBadge icon={TestTube} tone={run ? BADGE_TONE[run.status] : 'neutral'} />
        <div className="min-w-0 flex-1">
          <div className="text-fg truncate text-[13.5px] font-semibold">{walkthrough.title}</div>
          <div className="text-faint truncate text-[11.5px]">
            {walkthrough.instance} - {steps} step{steps === 1 ? '' : 's'}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-focus-within/card:opacity-100 group-hover/card:opacity-100">
          <IconButton label="Edit" onClick={onEdit}>
            <PencilSimple className="size-4" />
          </IconButton>
          <IconButton label="Delete" danger onClick={onDelete}>
            <Trash className="size-4" />
          </IconButton>
        </div>
      </div>

      <button
        type="button"
        disabled={!run}
        onClick={() => run && onOpen(run)}
        className={cn(
          'bg-canvas min-h-[58px] rounded-xl p-3 text-left transition-colors',
          run ? 'hover:bg-raised cursor-pointer' : 'cursor-default',
        )}
      >
        {run ? (
          <RunSummary run={run} />
        ) : (
          <span className="text-faint text-[12px]">No runs yet</span>
        )}
      </button>

      <div className="flex items-center gap-2">
        <Button variant="primary" size="sm" disabled={working} onClick={onRun}>
          {working ? <Spinner className="size-4" /> : <Play className="size-4" weight="fill" />}
          {working ? 'Running' : 'Run'}
        </Button>
        {run ? (
          <Button variant="ghost" size="sm" onClick={() => onOpen(run)}>
            Open run
          </Button>
        ) : null}
      </div>
    </article>
  )
}

function RunSummary({ run }: { run: WalkRun }) {
  const { total, done, passed, current } = counts(run)

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <StatusPill status={run.status} />
        <span className="text-faint text-[11.5px] tabular-nums">
          {passed}/{total} passed
        </span>
        <span className="text-faint ml-auto text-[11px]">{timeAgo(run.createdAt)}</span>
      </div>
      <Progress done={done} total={total} status={run.status} />
      {current ? <div className="text-muted truncate text-[11.5px]">{current.text}</div> : null}
    </div>
  )
}

function Progress({
  done,
  total,
  status,
}: {
  done: number
  total: number
  status: WalkStepStatus
}) {
  const pct = total ? Math.round((done / total) * 100) : 0

  return (
    <div className="bg-raised h-1.5 w-full overflow-hidden rounded-full">
      <div
        className={cn('h-full rounded-full transition-[width] duration-300', BAR_TONE[status])}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

function Recent({ runs, onOpen }: { runs: WalkRun[]; onOpen: (id: string) => void }) {
  return (
    <div className="mt-8">
      <div className="text-faint mb-2 text-[12px] font-medium">Other runs</div>
      <div className="space-y-1">
        {runs.slice(0, RECENT_LIMIT).map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => onOpen(r.id)}
            className="hover:bg-canvas text-text flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-[12.5px]"
          >
            <StatusDot status={r.status} />
            <span className="min-w-0 flex-1 truncate font-medium">{r.title}</span>
            <span className="text-faint shrink-0 text-[11px]">{r.instance}</span>
            <span className="text-faint shrink-0 text-[11px]">{timeAgo(r.createdAt)}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function EditorPanel({
  instance,
  walkthrough,
  onClose,
  onSaved,
  onRun,
}: {
  instance: string
  walkthrough?: Walkthrough
  onClose: () => void
  onSaved: () => Promise<void>
  onRun: (run: WalkRun) => void
}) {
  const [draft, setDraft] = useState<Draft>(() =>
    walkthrough
      ? {
          instance: walkthrough.instance,
          title: walkthrough.title,
          goal: walkthrough.goal,
          steps: toLines(walkthrough.steps),
        }
      : { instance, title: '', goal: '', steps: '' },
  )
  const [describe, setDescribe] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [busy, setBusy] = useState(false)
  const plan = fromDraft(draft)

  const draftWithAi = async () => {
    if (!describe.trim()) return

    setDrafting(true)
    try {
      const out = await api.draftWalkthrough(draft.instance, describe.trim())
      setDraft((d) => ({ ...d, title: out.title, goal: out.goal, steps: toLines(out.steps) }))
    } catch (e) {
      reportError(e as Error)
    } finally {
      setDrafting(false)
    }
  }

  const persist = async (): Promise<Walkthrough | undefined> => {
    if (!plan.steps.length) return undefined

    setBusy(true)
    try {
      const saved = walkthrough
        ? await api.updateWalkthrough(walkthrough.id, plan)
        : await api.createWalkthrough(plan)
      await onSaved()
      return saved
    } catch (e) {
      reportError(e as Error)
      return undefined
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    if (await persist()) onClose()
  }

  const saveAndRun = async () => {
    const saved = await persist()
    if (!saved) return

    try {
      onRun(await api.startWalkRun({ walkthroughId: saved.id }))
    } catch (e) {
      reportError(e as Error)
    }
    onClose()
  }

  return (
    <Drawer width={EDITOR_WIDTH} onClose={onClose}>
      <DrawerHeader
        title={walkthrough ? 'Edit walkthrough' : 'New walkthrough'}
        subtitle={draft.instance}
        onClose={onClose}
      />
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
        <div className="flex items-end gap-2">
          <Textarea
            fill
            rows={1}
            value={describe}
            onChange={(e) => setDescribe(e.target.value)}
            placeholder="Describe a test and let the agent draft the steps..."
            className="min-h-10"
          />
          <Button variant="secondary" disabled={drafting || !describe.trim()} onClick={draftWithAi}>
            {drafting ? <Spinner className="size-4" /> : null} Draft
          </Button>
        </div>

        <Field label="Title">
          <input
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            placeholder="Short name for this test"
            className="border-line-strong/70 focus:border-brand h-10 w-full rounded-full border px-4 text-[13px] outline-none"
          />
        </Field>
        <Field label="Goal">
          <input
            value={draft.goal}
            onChange={(e) => setDraft({ ...draft, goal: e.target.value })}
            placeholder="What should be true when it passes"
            className="border-line-strong/70 focus:border-brand h-10 w-full rounded-full border px-4 text-[13px] outline-none"
          />
        </Field>
        <Field label="Steps" hint="One per line">
          <Textarea
            value={draft.steps}
            onChange={(e) => setDraft({ ...draft, steps: e.target.value })}
            placeholder={
              'Open the Rules admin page\nClick New rule\nType "Test" in the name\nSave and confirm it shows in the list'
            }
            className="min-h-56"
          />
        </Field>
      </div>
      <div className="border-line flex items-center gap-2 border-t px-5 py-3">
        {walkthrough ? (
          <span className="text-faint text-[12px]">
            {plan.steps.length} step{plan.steps.length === 1 ? '' : 's'}
          </span>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Button variant="secondary" disabled={busy || !plan.steps.length} onClick={save}>
            Save
          </Button>
          <Button
            variant="primary"
            disabled={busy || !plan.steps.length || !draft.instance}
            onClick={saveAndRun}
          >
            {busy ? <Spinner className="size-4" /> : <Play className="size-4" weight="fill" />} Save
            and run
          </Button>
        </div>
      </div>
    </Drawer>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-muted flex items-center gap-2 text-[12px] font-medium">
        {label}
        {hint ? <span className="text-faint font-normal">{hint}</span> : null}
      </span>
      {children}
    </label>
  )
}

function RunPanel({
  run,
  onClose,
  onStop,
}: {
  run: WalkRun
  onClose: () => void
  onStop: () => void
}) {
  const working = WORKING.includes(run.status)
  const { total, passed } = counts(run)

  return (
    <Drawer width={RUN_WIDTH} onClose={onClose}>
      <DrawerHeader
        title={run.title}
        subtitle={`${run.instance} - ${passed}/${total} passed`}
        onClose={onClose}
      >
        {working ? (
          <Button variant="ghost" size="sm" onClick={onStop}>
            Stop
          </Button>
        ) : (
          <StatusPill status={run.status} />
        )}
      </DrawerHeader>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-5 py-4">
        {run.steps.map((step) => (
          <StepCard key={step.index} run={run} step={step} />
        ))}
      </div>
    </Drawer>
  )
}

function StepCard({ run, step }: { run: WalkRun; step: WalkStep }) {
  return (
    <div className="border-line rounded-xl border p-3">
      <div className="flex items-center gap-2">
        <StatusPill status={step.status} />
        <span className="min-w-0 flex-1 text-[12.5px] font-medium">{step.text}</span>
        {step.status === 'running' ? <Spinner className="text-brand size-3.5" /> : null}
      </div>
      {step.action ? <div className="text-muted mt-1 text-[11.5px]">{step.action}</div> : null}
      {step.detail ? <div className="text-faint mt-0.5 text-[11.5px]">{step.detail}</div> : null}
      {step.screenshot ? (
        <a
          href={api.walkShotUrl(run.id, step.screenshot)}
          target="_blank"
          rel="noreferrer"
          className="mt-2 block"
        >
          <img
            src={api.walkShotUrl(run.id, step.screenshot)}
            alt=""
            className="border-line max-h-60 w-full rounded-lg border object-cover object-top"
          />
        </a>
      ) : null}
    </div>
  )
}

function Drawer({
  width,
  onClose,
  children,
}: {
  width: string
  onClose: () => void
  children: ReactNode
}) {
  useLayer(onClose)

  return createPortal(
    <div className="fixed inset-0 z-[120]">
      <div className="animate-fade-in absolute inset-0 bg-black/20" onClick={onClose} />
      <div
        style={{ width }}
        className="animate-drawer-in border-line absolute inset-y-0 right-0 flex flex-col border-l bg-white shadow-[0_12px_40px_rgba(38,50,56,0.22)]"
      >
        {children}
      </div>
    </div>,
    document.body,
  )
}

function DrawerHeader({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string
  subtitle?: string
  onClose: () => void
  children?: ReactNode
}) {
  return (
    <div className="border-line flex h-16 shrink-0 items-center gap-3 border-b px-5">
      <div className="min-w-0 flex-1">
        <div className="text-fg truncate text-[14px] font-semibold">{title}</div>
        {subtitle ? <div className="text-faint truncate text-[12px]">{subtitle}</div> : null}
      </div>
      {children}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="text-muted hover:bg-canvas hover:text-fg flex size-8 shrink-0 items-center justify-center rounded-full transition-colors"
      >
        <X className="size-4" />
      </button>
    </div>
  )
}

function IconButton({
  label,
  danger,
  onClick,
  children,
}: {
  label: string
  danger?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        'flex size-7 items-center justify-center rounded-full transition-colors',
        danger
          ? 'text-muted hover:bg-danger-soft hover:text-danger'
          : 'text-muted hover:bg-canvas hover:text-fg',
      )}
    >
      {children}
    </button>
  )
}

function StatusPill({ status }: { status: WalkStepStatus }) {
  return (
    <span
      className={cn('rounded-full px-2 py-0.5 text-[10.5px] font-semibold', STATUS_TONE[status])}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

function StatusDot({ status }: { status: WalkStepStatus }) {
  return <span className={cn('size-2 shrink-0 rounded-full', BAR_TONE[status])} />
}
