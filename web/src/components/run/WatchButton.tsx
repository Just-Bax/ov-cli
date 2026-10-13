import { Eye as EyeIcon, X as XMarkIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunWatch } from '@shared/types.ts'
import { reportError } from '@/components/Toasts'
import { Button, Textarea } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

const EVERY_MINUTES = [5, 15, 30, 60]
const FOR_HOURS = [1, 4, 8, 24]

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

export function WatchChip({ runId, watch }: { runId: string; watch: RunWatch }) {
  return (
    <span
      title={watch.prompt}
      className="bg-brand-soft text-brand-strong inline-flex h-8 items-center gap-1.5 rounded-full pr-1 pl-3 text-[12px] font-medium"
    >
      <EyeIcon className="size-4" />
      Watching, next {clock(watch.nextAt)}
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

export function WatchDialog({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [prompt, setPrompt] = useState('')
  const [every, setEvery] = useState(15)
  const [hours, setHours] = useState(4)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const start = async () => {
    setSaving(true)
    try {
      await api.watch(runId, prompt.trim(), every, hours)
      onClose()
    } catch (e) {
      reportError(e)
    } finally {
      setSaving(false)
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-[#263238]/30 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-label="Watch this thread"
        className="animate-pop w-full max-w-[420px] rounded-2xl bg-white p-5 shadow-[0_20px_60px_rgba(38,50,56,0.25)]"
      >
        <div className="text-fg text-[15px] font-semibold">Watch this thread</div>
        <div className="text-muted mt-1 text-[12.5px] leading-relaxed">
          The agent rechecks on a schedule and answers here. Every check uses credits.
        </div>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What to check, e.g. is the staging queue back under 10k?"
          className="mt-4 min-h-[72px] text-[13px]"
          autoFocus
        />
        <div className="text-muted mt-4 mb-1.5 text-[11.5px] font-medium">Every</div>
        <Choice values={EVERY_MINUTES} value={every} unit="min" onChange={setEvery} />
        <div className="text-muted mt-3 mb-1.5 text-[11.5px] font-medium">For</div>
        <Choice values={FOR_HOURS} value={hours} unit="h" onChange={setHours} />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="lg" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="lg"
            disabled={!prompt.trim() || saving}
            onClick={() => void start()}
          >
            Start watching
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
