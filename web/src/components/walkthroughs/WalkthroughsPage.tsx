import { useEffect, useMemo, useState } from 'react'
import type { WalkPlanDraft, WalkRun, WalkStepStatus, Walkthrough } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button, Page, Select, Spinner, Textarea } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useInstances } from '@/lib/instances'
import { timeAgo } from '@/lib/time'

const INSTANCE_KEY = 'ov-agent.walkthrough-instance'

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

const WORKING: WalkStepStatus[] = ['pending', 'running']

type Draft = { instance: string; title: string; goal: string; steps: string }

function toLines(steps: string[]): string {
  return steps.join('\n')
}

function fromDraft(draft: Draft): WalkPlanDraft {
  const steps = draft.steps
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  return { instance: draft.instance, title: draft.title.trim(), goal: draft.goal.trim(), steps }
}

export function WalkthroughsPage() {
  const { instances } = useInstances()
  const signedIn = useMemo(() => (instances ?? []).filter((i) => i.valid), [instances])
  const [instance, setInstance] = useState(() => localStorage.getItem(INSTANCE_KEY) ?? '')
  const [saved, setSaved] = useState<Walkthrough[]>()
  const [runs, setRuns] = useState<WalkRun[]>([])
  const [editingId, setEditingId] = useState<string>()
  const [draft, setDraft] = useState<Draft>({ instance: '', title: '', goal: '', steps: '' })
  const [describe, setDescribe] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState<WalkRun>()

  const reload = () =>
    api.walkthroughs().then(({ walkthroughs, runs }) => {
      setSaved(walkthroughs)
      setRuns(runs)
    }, reportError)

  useEffect(() => void reload(), [])

  useEffect(() => {
    if (!instance && signedIn.length) setInstance(signedIn[0].host)
  }, [signedIn])

  useEffect(() => {
    if (instance) localStorage.setItem(INSTANCE_KEY, instance)
    setDraft((d) => ({ ...d, instance: instance }))
  }, [instance])

  useEffect(() => {
    if (!run || !WORKING.includes(run.status)) return

    const source = new EventSource(api.walkRunEventsUrl(run.id))
    source.onmessage = (e) => {
      const latest = JSON.parse(e.data) as WalkRun
      setRun(latest)
      if (!WORKING.includes(latest.status)) {
        source.close()
        void reload()
      }
    }
    source.onerror = () => source.close()
    return () => source.close()
  }, [run?.id, run?.status])

  const startNew = () => {
    setEditingId(undefined)
    setRun(undefined)
    setDescribe('')
    setDraft({ instance, title: '', goal: '', steps: '' })
  }

  const edit = (w: Walkthrough) => {
    setEditingId(w.id)
    setRun(undefined)
    setInstance(w.instance)
    setDraft({ instance: w.instance, title: w.title, goal: w.goal, steps: toLines(w.steps) })
  }

  const draftWithAi = async () => {
    if (!describe.trim()) return

    setDrafting(true)
    try {
      const plan = await api.draftWalkthrough(instance, describe.trim())
      setDraft({ instance, title: plan.title, goal: plan.goal, steps: toLines(plan.steps) })
    } catch (e) {
      reportError(e as Error)
    } finally {
      setDrafting(false)
    }
  }

  const save = async () => {
    const plan = fromDraft(draft)
    if (!plan.steps.length) return

    setBusy(true)
    try {
      const w = editingId
        ? await api.updateWalkthrough(editingId, plan)
        : await api.createWalkthrough(plan)
      setEditingId(w.id)
      await reload()
    } catch (e) {
      reportError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  const start = async (body: { walkthroughId?: string } & Partial<WalkPlanDraft>) => {
    setBusy(true)
    try {
      setRun(await api.startWalkRun(body))
    } catch (e) {
      reportError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (w: Walkthrough) => {
    await api.deleteWalkthrough(w.id).catch(reportError)
    if (editingId === w.id) startNew()
    await reload()
  }

  const actions = (
    <>
      <div className="w-[240px]">
        <Select
          value={instance}
          onChange={setInstance}
          placeholder={instances ? 'No signed-in instance' : 'Loading...'}
          options={signedIn.map((i) => ({ value: i.host, label: i.host }))}
        />
      </div>
      <Button variant="primary" onClick={startNew}>
        New walkthrough
      </Button>
    </>
  )

  const plan = fromDraft(draft)

  return (
    <Page
      title="Walkthroughs"
      subtitle="Browser tests a real user would run on an instance, checked by the fast model at every step."
      actions={actions}
    >
      <div className="mx-auto flex max-w-[1100px] gap-6 p-6">
        <aside className="w-[300px] shrink-0 space-y-5">
          <Saved saved={saved} editingId={editingId} onPick={edit} onDelete={remove} />
          <Recent runs={runs} activeId={run?.id} onPick={setRun} />
        </aside>

        <div className="min-w-0 flex-1 space-y-5">
          {run ? (
            <RunView run={run} onStop={() => void api.stopWalkRun(run.id).catch(reportError)} />
          ) : null}

          <section className="border-line-strong/70 space-y-4 rounded-2xl border p-5">
            <div className="flex items-center gap-2">
              <Textarea
                fill
                rows={1}
                value={describe}
                onChange={(e) => setDescribe(e.target.value)}
                placeholder="Describe a test and let the agent draft the steps..."
                className="min-h-10"
              />
              <Button
                variant="secondary"
                disabled={drafting || !describe.trim()}
                onClick={draftWithAi}
              >
                {drafting ? <Spinner className="size-4" /> : null} Draft
              </Button>
            </div>

            <input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="Title"
              className="border-line-strong/70 h-10 w-full rounded-full border px-4 text-[13px] outline-none"
            />
            <Textarea
              value={draft.steps}
              onChange={(e) => setDraft({ ...draft, steps: e.target.value })}
              placeholder={
                'One step per line, e.g.\nOpen the Rules admin page\nClick New rule\nType "Test" in the name\nSave and confirm it shows in the list'
              }
              className="min-h-48"
            />

            <div className="flex items-center gap-2">
              <Button variant="secondary" disabled={busy || !plan.steps.length} onClick={save}>
                {editingId ? 'Save changes' : 'Save walkthrough'}
              </Button>
              <Button
                variant="primary"
                disabled={busy || !plan.steps.length || !instance}
                onClick={() => void start(editingId ? { walkthroughId: editingId } : plan)}
              >
                Run
              </Button>
              <span className="text-faint text-[12px]">
                {plan.steps.length} step{plan.steps.length === 1 ? '' : 's'} on{' '}
                {instance || 'no instance'}
              </span>
            </div>
          </section>
        </div>
      </div>
    </Page>
  )
}

function Saved({
  saved,
  editingId,
  onPick,
  onDelete,
}: {
  saved: Walkthrough[] | undefined
  editingId: string | undefined
  onPick: (w: Walkthrough) => void
  onDelete: (w: Walkthrough) => void
}) {
  return (
    <div>
      <div className="text-faint mb-2 px-1 text-[12px] font-medium">Saved</div>
      {saved && !saved.length ? (
        <div className="text-faint px-1 text-[12.5px]">None yet. Draft one on the right.</div>
      ) : null}
      <div className="space-y-1">
        {saved?.map((w) => (
          <div
            key={w.id}
            className={cn(
              'group/w flex items-center gap-2 rounded-xl px-3 py-2 text-[12.5px]',
              editingId === w.id ? 'bg-brand-soft text-brand-strong' : 'hover:bg-canvas text-text',
            )}
          >
            <button type="button" onClick={() => onPick(w)} className="min-w-0 flex-1 text-left">
              <div className="truncate font-medium">{w.title}</div>
              <div className="text-faint truncate text-[11.5px]">
                {w.instance} - {w.steps.length} steps
              </div>
            </button>
            <button
              type="button"
              onClick={() => onDelete(w)}
              className="text-faint hover:text-danger shrink-0 opacity-0 group-hover/w:opacity-100"
            >
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function Recent({
  runs,
  activeId,
  onPick,
}: {
  runs: WalkRun[]
  activeId: string | undefined
  onPick: (r: WalkRun) => void
}) {
  if (!runs.length) return null

  return (
    <div>
      <div className="text-faint mb-2 px-1 text-[12px] font-medium">Recent runs</div>
      <div className="space-y-1">
        {runs.slice(0, 12).map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => onPick(r)}
            className={cn(
              'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[12.5px]',
              activeId === r.id ? 'bg-brand-soft text-brand-strong' : 'hover:bg-canvas text-text',
            )}
          >
            <StatusDot status={r.status} />
            <span className="min-w-0 flex-1 truncate">{r.title}</span>
            <span className="text-faint shrink-0 text-[11px]">{timeAgo(r.createdAt)}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function RunView({ run, onStop }: { run: WalkRun; onStop: () => void }) {
  const working = WORKING.includes(run.status)
  const passed = run.steps.filter((s) => s.status === 'passed').length

  return (
    <section className="border-line-strong/70 rounded-2xl border p-5">
      <div className="mb-3 flex items-center gap-2">
        <StatusDot status={run.status} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-semibold">{run.title}</div>
          <div className="text-faint text-[12px]">
            {run.instance} - {passed}/{run.steps.length} passed
          </div>
        </div>
        {working ? (
          <Button variant="ghost" onClick={onStop}>
            Stop
          </Button>
        ) : (
          <StatusPill status={run.status} />
        )}
      </div>
      <ol className="space-y-2">
        {run.steps.map((step) => (
          <li key={step.index} className="border-line rounded-xl border p-3">
            <div className="flex items-center gap-2">
              <StatusPill status={step.status} />
              <span className="min-w-0 flex-1 text-[12.5px] font-medium">{step.text}</span>
              {step.status === 'running' ? <Spinner className="text-brand size-3.5" /> : null}
            </div>
            {step.action ? (
              <div className="text-muted mt-1 text-[11.5px]">{step.action}</div>
            ) : null}
            {step.detail ? (
              <div className="text-faint mt-0.5 text-[11.5px]">{step.detail}</div>
            ) : null}
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
                  className="border-line max-h-56 w-full rounded-lg border object-cover object-top"
                />
              </a>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
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
  const tone =
    status === 'passed'
      ? 'bg-ok'
      : status === 'running' || status === 'pending'
        ? 'bg-brand'
        : status === 'blocked'
          ? 'bg-warn'
          : 'bg-danger'
  return <span className={cn('size-2 shrink-0 rounded-full', tone)} />
}
