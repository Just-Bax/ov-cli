import { EyeIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { useEffect, useRef, useState } from 'react'
import type { RunWatch } from '@shared/types.ts'
import { reportError } from '@/components/Toasts'
import { Button, Textarea } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

const EVERY_MINUTES = [5, 15, 30, 60]
const FOR_HOURS = [1, 4, 8, 24]
const MINUTE_MS = 60_000

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function Choice({
  values,
  value,
  unit,
  onChange,
}: {
  values: number[]
  value: number
  unit: string
  onChange: (v: number) => void
}) {
  return (
    <div className="bg-raised flex rounded-full p-1">
      {values.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            'h-7 flex-1 rounded-full px-2.5 text-[12px] font-medium transition-colors',
            v === value ? 'text-fg bg-white shadow-sm' : 'text-muted hover:text-fg',
          )}
        >
          {v} {unit}
        </button>
      ))}
    </div>
  )
}

export function WatchButton({ runId, watch }: { runId: string; watch?: RunWatch }) {
  const [open, setOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [every, setEvery] = useState(15)
  const [hours, setHours] = useState(4)
  const [saving, setSaving] = useState(false)
  const box = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  if (watch) {
    return (
      <span
        title={watch.prompt}
        className="bg-brand-soft text-brand-strong inline-flex h-8 items-center gap-1.5 rounded-full pr-1 pl-3 text-[12px] font-medium"
      >
        <EyeIcon className="size-4" />
        Every {Math.round(watch.everyMs / MINUTE_MS)} min, next {clock(watch.nextAt)}
        <button
          type="button"
          aria-label="Stop watching"
          title="Stop watching"
          onClick={() => void api.unwatch(runId).catch(reportError)}
          className="hover:bg-brand/15 flex size-6 items-center justify-center rounded-full"
        >
          <XMarkIcon className="size-3.5" />
        </button>
      </span>
    )
  }

  const start = async () => {
    setSaving(true)
    try {
      await api.watch(runId, prompt.trim(), every, hours)
      setOpen(false)
      setPrompt('')
    } catch (e) {
      reportError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <span ref={box} className="relative">
      <Button
        variant="ghost"
        title="Have the agent recheck something on a schedule"
        onClick={() => setOpen((v) => !v)}
      >
        <EyeIcon className="size-4" />
        Watch
      </Button>
      {open ? (
        <div className="border-line animate-pop absolute top-full right-0 z-40 mt-1.5 w-[360px] rounded-2xl border bg-white p-4 shadow-[0_6px_20px_rgba(38,50,56,0.14)]">
          <div className="text-fg text-[13.5px] font-semibold">Watch this thread</div>
          <div className="text-muted mt-0.5 text-[12px] leading-relaxed">
            The agent rechecks on a schedule and answers in this thread; you get a notification when
            each check is done. Every check uses credits.
          </div>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="What to check, e.g. is the staging queue back under 10k?"
            className="mt-3 min-h-[72px] text-[13px]"
            autoFocus
          />
          <div className="text-muted mt-3 mb-1 text-[11.5px] font-medium">Every</div>
          <Choice values={EVERY_MINUTES} value={every} unit="min" onChange={setEvery} />
          <div className="text-muted mt-3 mb-1 text-[11.5px] font-medium">For</div>
          <Choice values={FOR_HOURS} value={hours} unit="h" onChange={setHours} />
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!prompt.trim() || saving}
              onClick={() => void start()}
            >
              Start watching
            </Button>
          </div>
        </div>
      ) : null}
    </span>
  )
}
