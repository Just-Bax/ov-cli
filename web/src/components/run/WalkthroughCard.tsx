import { CaretDown, PencilSimple, Play, TestTube } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { WalkRun, Walkthrough } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { Button, IconBadge, Spinner, Textarea } from '@/components/common/ui'
import {
  BADGE_TONE,
  counts,
  Progress,
  StatusPill,
  StepCard,
  WORKING,
} from '@/components/walkthroughs/parts'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

function toLines(steps: string[]): string {
  return steps.join('\n')
}

export function WalkthroughCard({ walkthrough }: { walkthrough: Walkthrough }) {
  const [walk, setWalk] = useState(walkthrough)
  const [run, setRun] = useState<WalkRun>()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showSteps, setShowSteps] = useState(false)

  useEffect(() => {
    let alive = true
    api.walkthroughs().then(({ walkthroughs, runs }) => {
      if (!alive) return
      const live = walkthroughs.find((w) => w.id === walkthrough.id)
      if (live) setWalk(live)
      const last = runs.find((r) => r.walkthroughId === walkthrough.id)
      if (last) setRun(last)
    }, reportError)
    return () => {
      alive = false
    }
  }, [walkthrough.id])

  useEffect(() => {
    if (!run || !WORKING.includes(run.status)) return

    const source = new EventSource(api.walkRunEventsUrl(run.id))
    source.onmessage = (e) => {
      const latest = JSON.parse(e.data) as WalkRun
      setRun(latest)
      if (!WORKING.includes(latest.status)) source.close()
    }
    source.onerror = () => source.close()
    return () => source.close()
  }, [run?.id, run?.status])

  const working = run ? WORKING.includes(run.status) : false

  const start = async () => {
    setBusy(true)
    try {
      setRun(await api.startWalkRun({ walkthroughId: walk.id }))
      setShowSteps(true)
    } catch (e) {
      reportError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  const save = async (title: string, goal: string, stepsText: string) => {
    const steps = stepsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    if (!steps.length) return

    setBusy(true)
    try {
      const updated = await api.updateWalkthrough(walk.id, {
        instance: walk.instance,
        title: title.trim() || walk.title,
        goal: goal.trim(),
        steps,
      })
      setWalk(updated)
      setEditing(false)
    } catch (e) {
      reportError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-line-strong/70 rounded-2xl border bg-white">
      <div className="flex items-start gap-3 p-4">
        <IconBadge icon={TestTube} tone={run ? BADGE_TONE[run.status] : 'brand'} />
        <div className="min-w-0 flex-1">
          <div className="text-fg truncate text-[13.5px] font-semibold">{walk.title}</div>
          <div className="text-faint truncate text-[11.5px]">
            {walk.instance} - {walk.steps.length} step{walk.steps.length === 1 ? '' : 's'}
          </div>
        </div>
        {run ? <StatusPill status={run.status} /> : null}
      </div>

      {editing ? (
        <Editor walk={walk} busy={busy} onCancel={() => setEditing(false)} onSave={save} />
      ) : (
        <div className="px-4 pb-4">
          {walk.goal && walk.goal !== walk.title ? (
            <div className="text-muted mb-2 text-[12px]">{walk.goal}</div>
          ) : null}
          <button
            type="button"
            onClick={() => setShowSteps((v) => !v)}
            className="text-faint hover:text-fg flex items-center gap-1 text-[11.5px] font-medium"
          >
            <CaretDown className={cn('size-3 transition-transform', !showSteps && '-rotate-90')} />
            {showSteps ? 'Hide steps' : `Show ${walk.steps.length} steps`}
          </button>

          {showSteps ? (
            <ol className="mt-2 space-y-1">
              {walk.steps.map((step, i) => (
                <li key={i} className="flex gap-2 text-[12.5px]">
                  <span className="text-faint w-4 shrink-0 text-right tabular-nums">{i + 1}</span>
                  <span className="text-text min-w-0">{step}</span>
                </li>
              ))}
            </ol>
          ) : null}

          {run && showSteps ? <RunSteps run={run} /> : null}

          <div className="mt-3 flex items-center gap-2">
            <Button variant="primary" size="sm" disabled={busy || working} onClick={start}>
              {busy || working ? (
                <Spinner className="size-4" />
              ) : (
                <Play className="size-4" weight="fill" />
              )}
              {working ? 'Running' : run ? 'Run again' : 'Run'}
            </Button>
            {working ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => run && void api.stopWalkRun(run.id).catch(reportError)}
              >
                Stop
              </Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
                <PencilSimple className="size-4" /> Edit
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function RunSteps({ run }: { run: WalkRun }) {
  const { total, done, passed } = counts(run)

  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-faint text-[11.5px] tabular-nums">
          {passed}/{total} passed
        </span>
      </div>
      <Progress done={done} total={total} status={run.status} />
      <div className="space-y-2">
        {run.steps.map((step) => (
          <StepCard key={step.index} run={run} step={step} />
        ))}
      </div>
    </div>
  )
}

function Editor({
  walk,
  busy,
  onCancel,
  onSave,
}: {
  walk: Walkthrough
  busy: boolean
  onCancel: () => void
  onSave: (title: string, goal: string, steps: string) => void
}) {
  const [title, setTitle] = useState(walk.title)
  const [goal, setGoal] = useState(walk.goal)
  const [steps, setSteps] = useState(toLines(walk.steps))

  return (
    <div className="space-y-2 px-4 pb-4">
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        className="border-line-strong/70 focus:border-brand h-9 w-full rounded-full border px-3.5 text-[13px] outline-none"
      />
      <input
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        placeholder="Goal"
        className="border-line-strong/70 focus:border-brand h-9 w-full rounded-full border px-3.5 text-[13px] outline-none"
      />
      <Textarea
        value={steps}
        onChange={(e) => setSteps(e.target.value)}
        placeholder="One step per line"
        className="min-h-32"
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || !steps.trim()}
          onClick={() => onSave(title, goal, steps)}
        >
          Save
        </Button>
      </div>
    </div>
  )
}
