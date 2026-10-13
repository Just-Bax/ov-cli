import { go } from '@/lib/route'

const KEY = 'ov-agent.draft'
export const DRAFT_EVENT = 'ov-agent:draft'

type Draft = { prompt: string; instance?: string }

export function openDraft(draft: Draft): void {
  sessionStorage.setItem(KEY, JSON.stringify(draft))
  go({ page: 'home' })
  window.dispatchEvent(new Event(DRAFT_EVENT))
}

export function takeDraft(): Draft | undefined {
  const raw = sessionStorage.getItem(KEY)
  sessionStorage.removeItem(KEY)
  return raw ? (JSON.parse(raw) as Draft) : undefined
}
