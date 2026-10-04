import { go } from '@/lib/route'

const KEY = 'ov-agent.draft'

export type Draft = { prompt: string; instance?: string }

// "Ask the agent" buttons hand a prompt to New run instead of starting a run, so the user can
// edit or add to it before sending.
export function openDraft(draft: Draft): void {
  sessionStorage.setItem(KEY, JSON.stringify(draft))
  go({ page: 'home' })
  window.dispatchEvent(new Event('ov-agent:draft'))
}

export function takeDraft(): Draft | undefined {
  const raw = sessionStorage.getItem(KEY)
  sessionStorage.removeItem(KEY)
  try {
    return raw ? (JSON.parse(raw) as Draft) : undefined
  } catch {
    return undefined
  }
}
