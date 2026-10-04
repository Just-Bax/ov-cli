import { Clock } from 'lucide-react'
import { useEffect, useState } from 'react'
import { formatMinutes } from '@shared/estimate.ts'
import type { SavedTotals, Settings } from '@shared/types.ts'
import { Composer } from '@/components/Composer'
import { defaultInstance, InstancePicker, useInstances } from '@/components/InstancePicker'
import { ModelPicker } from '@/components/ModelPicker'
import { WriteSwitch } from '@/components/WriteSwitch'
import { Page } from '@/components/ui'
import { api } from '@/lib/api'
import { go } from '@/lib/route'

const EXAMPLES = [
  'Which rules failed in the last 24 hours, and why?',
  'Why did the last run of the import fail? Show the row errors.',
  'Which Vizion Hub modules failed this week? Read their logs.',
  'Which emails failed to send today, and what was the error?',
]

const WORDS = ['troubleshooting', 'investigating', 'configuring', 'automating', 'fixing']
const WORD_MS = 2800

function RotatingWord() {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setIndex((i) => (i + 1) % WORDS.length), WORD_MS)
    return () => clearInterval(timer)
  }, [])
  const word = WORDS[index]
  return (
    <span key={word} data-text={word} className="word-cycle">
      {word}
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

  useEffect(() => {
    api
      .stats()
      .then(setTotals)
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    if (instances && !instance) setInstance(defaultInstance(instances, settings.defaultInstance))
  }, [instances])

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

          {totals?.all.minutes ? (
            <div className="text-muted mt-8 flex items-center justify-center gap-2 text-[12.5px]">
              <Clock className="text-ok size-3.5" />
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

          <div className="mt-8 grid gap-2 sm:grid-cols-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                disabled={starting}
                onClick={() => void submit(example, [])}
                className="border-line hover:border-line-strong hover:bg-raised text-text rounded-xl border p-3 text-left text-[13px] leading-snug transition-colors"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Page>
  )
}
