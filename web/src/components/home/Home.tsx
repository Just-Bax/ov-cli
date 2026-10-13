import { useEffect, useState } from 'react'
import type { Settings } from '@shared/types.ts'
import { Composer } from '@/components/composer/Composer'
import { InstancePicker } from '@/components/composer/InstancePicker'
import { ModelPicker } from '@/components/composer/ModelPicker'
import { WriteSwitch } from '@/components/composer/WriteSwitch'
import { Page } from '@/components/common/ui'
import { api } from '@/lib/api'
import { DRAFT_EVENT, takeDraft } from '@/lib/draft'
import { useWindowEvent } from '@/lib/hooks'
import { useInstances } from '@/lib/instances'
import { cn } from '@/lib/cn'
import { go } from '@/lib/route'
import { refreshRuns } from '@/lib/runs'

const WORDS = ['troubleshooting', 'investigating', 'configuring', 'automating', 'fixing']
const WORD_MS = 4500
const FADE_MS = 500
const NOON_HOUR = 12
const EVENING_HOUR = 18
const CHOICES_KEY = 'ov-agent.new-run-choices'

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
  return h < NOON_HOUR ? 'Good morning' : h < EVENING_HOUR ? 'Good afternoon' : 'Good evening'
}

type Choices = { model?: string; instance?: string; allowWrite?: boolean }

function loadChoices(): Choices {
  const raw = localStorage.getItem(CHOICES_KEY)
  return raw ? (JSON.parse(raw) as Choices) : {}
}

export function Home({ settings }: { settings: Settings }) {
  const saved = loadChoices()
  const { instances } = useInstances()
  const [model, setModel] = useState(saved.model ?? settings.defaultModel)
  const [instance, setInstance] = useState(saved.instance ?? '')
  const [allowWrite, setAllowWrite] = useState(saved.allowWrite ?? false)
  const [error, setError] = useState<string>()
  const [starting, setStarting] = useState(false)
  const [draft, setDraft] = useState<{ text: string; at: number }>()

  useEffect(() => {
    localStorage.setItem(CHOICES_KEY, JSON.stringify({ model, instance, allowWrite }))
  }, [model, instance, allowWrite])

  const loadDraft = () => {
    const found = takeDraft()
    if (!found) return
    setDraft({ text: found.prompt, at: Date.now() })
    if (found.instance) setInstance(found.instance)
  }

  useEffect(loadDraft, [])
  useWindowEvent(DRAFT_EVENT, loadDraft)

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
      void refreshRuns()
      go({ page: 'run', id })
    } catch (e) {
      setError((e as Error).message)
      setStarting(false)
      throw e
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
            draftKey="new-run"
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
        </div>
      </div>
    </Page>
  )
}
