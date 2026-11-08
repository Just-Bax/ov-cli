import type { Access } from '@shared/types.ts'
import { useEffect, useState } from 'react'
import { AccessPicker, accessMode } from '@/components/composer/AccessPicker'
import { Composer } from '@/components/composer/Composer'
import { instanceCommand, useAccessCommand } from '@/components/composer/commands'
import { InstancePicker } from '@/components/composer/InstancePicker'
import { Button, Page } from '@/components/common/ui'
import { api } from '@/lib/api'
import { DRAFT_EVENT, takeDraft } from '@/lib/draft'
import { useWindowEvent } from '@/lib/hooks'
import { useInstances } from '@/lib/instances'
import { cn } from '@/lib/cn'
import { prefersReducedMotion } from '@/lib/motion'
import { go } from '@/lib/route'
import { PROVIDER_BRANDS } from '@/lib/providerBrand'
import { refreshRuns } from '@/lib/runs'
import { providerStatus, useSettings } from '@/lib/settings'

const WORDS = ['investigating', 'configuring', 'building', 'automating', 'fixing']
const WORD_MS = 4500
const FADE_MS = 500
const NOON_HOUR = 12
const EVENING_HOUR = 18
const CHOICES_KEY = 'ov-agent.new-run-choices'

function RotatingWord() {
  const [index, setIndex] = useState(0)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    if (prefersReducedMotion()) return

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

type Choices = { access?: Access }

function loadChoices(): Choices {
  const raw = localStorage.getItem(CHOICES_KEY)
  return raw ? (JSON.parse(raw) as Choices) : {}
}

function ProviderNotice() {
  const { settings, providers } = useSettings()
  const current = providerStatus(providers, settings.provider)
  if (current.account.signedIn && settings.defaultModel) return null

  const name = PROVIDER_BRANDS[current.id].name
  const missing = current.account.signedIn ? 'has no main model picked' : 'is not set up yet'

  return (
    <div className="bg-warn-soft text-fg mb-4 flex items-center gap-3 rounded-2xl px-4 py-3 text-[12.5px]">
      <span className="flex-1">
        {name} {missing}, so new threads cannot start.
      </span>
      <Button size="sm" variant="primary" onClick={() => go({ page: 'settings' })}>
        Open Settings
      </Button>
    </div>
  )
}

export function Home() {
  const saved = loadChoices()
  const { instances } = useInstances()
  const [instance, setInstance] = useState('')
  const [access, setAccess] = useState<Access>(saved.access ?? 'read')
  const [error, setError] = useState<string>()
  const [starting, setStarting] = useState(false)
  const [draft, setDraft] = useState<{ text: string; at: number }>()

  useEffect(() => {
    localStorage.setItem(CHOICES_KEY, JSON.stringify({ access }))
  }, [access])

  const loadDraft = () => {
    const found = takeDraft()
    if (!found) return
    setDraft({ text: found.prompt, at: Date.now() })
    if (found.instance) setInstance(found.instance)
  }

  useEffect(loadDraft, [])
  useWindowEvent(DRAFT_EVENT, loadDraft)

  const commands = [instanceCommand(instances ?? [], setInstance), useAccessCommand(setAccess)]

  const submit = async (text: string, files: File[]) => {
    setStarting(true)
    setError(undefined)

    try {
      const attachments = files.length ? await api.upload(files) : []

      const { id } = await api.startRun({
        prompt: text.trim(),
        instance: instance || undefined,
        attachments,
        access,
      })

      void refreshRuns()
      go({ page: 'thread', id })
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
          <ProviderNotice />
          <Composer
            autoFocus
            size="lg"
            allowFiles
            busy={starting}
            placeholder="Ask about an instance, describe a problem, or paste a case number or errors"
            onSend={submit}
            draft={draft}
            draftKey="new-run"
            commands={commands}
            instance={instance || undefined}
            extras={
              <>
                {instances?.length ? (
                  <InstancePicker value={instance} onChange={setInstance} instances={instances} />
                ) : null}
                <AccessPicker value={access} onChange={setAccess} />
              </>
            }
          />
          <div className="text-faint mt-2 px-2 text-center text-[11.5px]">
            {accessMode(access).label}: {accessMode(access).about}
          </div>
          {error ? <div className="text-danger mt-2 text-center text-[12.5px]">{error}</div> : null}
        </div>
      </div>
    </Page>
  )
}
