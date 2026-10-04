import {
  ClockIcon,
  DocumentArrowUpIcon,
  EnvelopeIcon,
  ExclamationTriangleIcon,
  RectangleStackIcon,
  ShareIcon,
} from '@heroicons/react/24/outline'
import type { Icon } from '@/components/ui'
import { useEffect, useState } from 'react'
import { formatMinutes } from '@shared/estimate.ts'
import type { SavedTotals, Settings } from '@shared/types.ts'
import { Composer } from '@/components/Composer'
import { InstancePicker, useInstances } from '@/components/InstancePicker'
import { ModelPicker } from '@/components/ModelPicker'
import { WriteSwitch } from '@/components/WriteSwitch'
import { Page } from '@/components/ui'
import { api } from '@/lib/api'
import { takeDraft } from '@/lib/draft'
import { cn } from '@/lib/cn'
import { go } from '@/lib/route'

const EXAMPLES: { label: string; icon: Icon; prompt: string }[] = [
  {
    label: 'Failed rules',
    icon: ShareIcon,
    prompt: 'Which rules failed in the last 24 hours, and why?',
  },
  {
    label: 'Import errors',
    icon: DocumentArrowUpIcon,
    prompt: 'Why did the last run of the import fail? Show the row errors.',
  },
  {
    label: 'Module failures',
    icon: RectangleStackIcon,
    prompt: 'Which Vizion Hub modules failed this week? Read their logs.',
  },
  {
    label: 'Email failures',
    icon: EnvelopeIcon,
    prompt: 'Which emails failed to send today, and what was the error?',
  },
  {
    label: 'Recent errors',
    icon: ExclamationTriangleIcon,
    prompt: 'What errors did users hit in the last 24 hours, and what caused them?',
  },
]

const WORDS = ['troubleshooting', 'investigating', 'configuring', 'automating', 'fixing']
const WORD_MS = 4500
const FADE_MS = 500

function RotatingWord() {
  const [index, setIndex] = useState(0)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    let swap: ReturnType<typeof setTimeout> | undefined
    const timer = setInterval(() => {
      setLeaving(true)
      swap = setTimeout(() => {
        setIndex((i) => (i + 1) % WORDS.length)
        setLeaving(false)
      }, FADE_MS)
    }, WORD_MS)
    return () => {
      clearInterval(timer)
      clearTimeout(swap)
    }
  }, [])

  return (
    <span key={index} className={cn('word-cycle', leaving ? 'word-out' : 'word-in')}>
      {WORDS[index]}
    </span>
  )
}

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function Home({ settings }: { settings: Settings }) {
  const [model, setModel] = useState(settings.defaultModel)
  const { instances } = useInstances()
  const [instance, setInstance] = useState('')
  const [allowWrite, setAllowWrite] = useState(false)
  const [error, setError] = useState<string>()
  const [starting, setStarting] = useState(false)
  const [totals, setTotals] = useState<SavedTotals>()
  const [draft, setDraft] = useState<{ text: string; at: number }>()

  useEffect(() => {
    const load = () => {
      const found = takeDraft()
      if (!found) return
      setDraft({ text: found.prompt, at: Date.now() })
      if (found.instance) setInstance(found.instance)
    }
    load()
    window.addEventListener('ov-agent:draft', load)
    return () => window.removeEventListener('ov-agent:draft', load)
  }, [])

  useEffect(() => {
    api
      .stats()
      .then(setTotals)
      .catch(() => undefined)
  }, [])

  const submit = async (text: string, files: File[]) => {
    setStarting(true)
    setError(undefined)
    try {
      const attachments = files.length ? await api.upload(files) : []
      const { id } = await api.startRun({
        prompt: text.trim(),
        instance: instance || undefined,
        attachments,
        model,
        allowWrite,
      })
      go({ page: 'run', id })
    } catch (e) {
      setError((e as Error).message)
      setStarting(false)
    }
  }

  return (
    <Page>
      <div className="flex min-h-full flex-col items-center justify-center px-6 py-12">
        <div className="w-full max-w-[760px]">
          <h1 className="text-fg mb-6 text-center text-[26px] font-semibold tracking-tight">
            {greeting()}. What are we <RotatingWord />?
          </h1>
          <Composer
            autoFocus
            size="lg"
            allowFiles
            busy={starting}
            placeholder="Case number or trackor link, or describe the problem and paste errors"
            onSend={submit}
            draft={draft}
            extras={
              <>
                {instances?.length ? (
                  <InstancePicker value={instance} onChange={setInstance} instances={instances} />
                ) : null}
                <ModelPicker value={model} onChange={setModel} />
                <WriteSwitch value={allowWrite} onChange={setAllowWrite} />
              </>
            }
          />
          <div className="text-faint mt-2 px-2 text-center text-[11.5px]">
            {allowWrite
              ? 'Changes allowed for this run. Each change waits for your Approve.'
              : 'Read-only on every instance. Changes come back as diffs for you to apply.'}
          </div>
          {error ? <div className="text-danger mt-2 text-center text-[12.5px]">{error}</div> : null}

          {settings.showTimeSaved && totals?.all.minutes ? (
            <div className="text-muted mt-8 flex items-center justify-center gap-2 text-[12.5px]">
              <ClockIcon className="text-ok size-3.5" />
              <span>
                <span className="text-ok font-semibold">~{formatMinutes(totals.week.minutes)}</span>{' '}
                saved this week across {totals.week.runs} run{totals.week.runs === 1 ? '' : 's'}
              </span>
              <span className="text-faint">-</span>
              <span>{formatMinutes(totals.month.minutes)} in 30 days</span>
              <span className="text-faint">-</span>
              <span>{formatMinutes(totals.all.minutes)} total</span>
            </div>
          ) : null}

          <div className="mt-8 flex flex-wrap justify-center gap-2">
            {EXAMPLES.map(({ label, icon: Icon, prompt }) => (
              <button
                key={label}
                type="button"
                title={prompt}
                disabled={starting}
                onClick={() => setDraft({ text: prompt, at: Date.now() })}
                className="border-line-strong/70 text-text hover:bg-raised hover:border-line-strong flex h-9 items-center gap-2 rounded-full border bg-white px-4 text-[13px] transition-colors"
              >
                <Icon className="text-brand size-4" />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Page>
  )
}
