import type { PreviousSignIn, SignInMode } from '@shared/types.ts'
import type { Tone } from '@/components/common/ui'
import { DAY_MS, HOUR_MS, timeAgo, timeWithDay } from '@/lib/time'

export const REMEMBER_DAYS = 30
const RENEW_WITHIN_MS = 3 * DAY_MS
const SESSION_RECENT_MS = HOUR_MS
const DATE: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }

const KIND_LABEL: Record<SignInMode, string> = {
  session: 'Web session',
  remembered: `${REMEMBER_DAYS}-day token`,
  token: 'Your API token',
}

export const KINDS_HINT = `A web session asks again when the instance ends it. A ${REMEMBER_DAYS}-day token asks again on its date. Your own API token asks again when it expires.`

type Stage = 'ok' | 'unknown' | 'soon' | 'expired' | 'ended'

export type SignInState = {
  stage: Stage
  summary: string
  chip?: { tone: Tone; text: string }
}

export function dayOf(ts: number): string {
  return new Date(ts).toLocaleDateString([], DATE)
}

export function rememberedUntil(): string {
  return dayOf(Date.now() + REMEMBER_DAYS * DAY_MS)
}

function daysLeft(ts: number): number {
  return Math.max(0, Math.ceil((ts - Date.now()) / DAY_MS))
}

function sessionState(s: PreviousSignIn): SignInState {
  const kind = KIND_LABEL.session
  if (s.endedAt)
    return {
      stage: 'ended',
      summary: `${kind}, ended ${timeWithDay(s.endedAt, DATE)}`,
      chip: { tone: 'neutral', text: 'Signed out' },
    }

  if (!s.lastWorkedAt) return { stage: 'unknown', summary: 'Not signed in' }

  if (Date.now() - s.lastWorkedAt >= SESSION_RECENT_MS)
    return { stage: 'unknown', summary: `${kind}, last worked ${timeAgo(s.lastWorkedAt)}` }

  return {
    stage: 'ok',
    summary: `${kind}, worked ${timeAgo(s.lastWorkedAt)}`,
    chip: { tone: 'ok', text: 'Signed in' },
  }
}

function tokenState(s: PreviousSignIn): SignInState {
  const kind = KIND_LABEL[s.mode]
  if (s.endedAt)
    return {
      stage: 'ended',
      summary: `${kind}, rejected by the instance`,
      chip: { tone: 'danger', text: 'Rejected' },
    }

  if (!s.expiresAt) return { stage: 'ok', summary: kind, chip: { tone: 'ok', text: 'Signed in' } }

  const until = dayOf(s.expiresAt)
  if (s.expiresAt <= Date.now())
    return {
      stage: 'expired',
      summary: `${kind}, expired ${until}`,
      chip: { tone: 'neutral', text: 'Expired' },
    }

  if (s.expiresAt - Date.now() < RENEW_WITHIN_MS)
    return {
      stage: 'soon',
      summary: `${kind}, expires ${until} (in ${daysLeft(s.expiresAt)} days)`,
      chip: { tone: 'warn', text: 'Expires soon' },
    }

  return {
    stage: 'ok',
    summary: `${kind}, until ${until}`,
    chip: { tone: 'ok', text: 'Signed in' },
  }
}

export function signInState(s: PreviousSignIn): SignInState {
  return s.mode === 'session' ? sessionState(s) : tokenState(s)
}

export function signInReason(previous?: PreviousSignIn): string {
  if (!previous) return 'The agent needs it to continue.'

  if (previous.mode === 'session')
    return `Its web session ended. Sign in for ${REMEMBER_DAYS} days so this doesn't keep happening.`

  if (previous.mode === 'token')
    return 'Your API token was rejected or expired. Paste a new one from Admin > Auth Tokens.'

  return signInState(previous).stage === 'expired'
    ? `Its ${REMEMBER_DAYS}-day token expired ${dayOf(previous.expiresAt!)}. Sign in once more for another ${REMEMBER_DAYS} days.`
    : `Its ${REMEMBER_DAYS}-day token was rejected. Sign in again for a new one.`
}
