export const SECOND_MS = 1000
export const MINUTE_MS = 60 * SECOND_MS
export const HOUR_MS = 60 * MINUTE_MS
export const DAY_MS = 24 * HOUR_MS
const WEEK_MS = 7 * DAY_MS

const CLOCK: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }

export function shortSpan(ms: number): string {
  const span = Math.max(0, ms)
  if (span < MINUTE_MS) return 'now'
  if (span < HOUR_MS) return `${Math.round(span / MINUTE_MS)}m`
  if (span < DAY_MS) return `${Math.round(span / HOUR_MS)}h`
  if (span < WEEK_MS) return `${Math.round(span / DAY_MS)}d`
  return `${Math.round(span / WEEK_MS)}w`
}

export function timeAgo(ts: number | string): string {
  const t = typeof ts === 'number' ? ts : Date.parse(ts)
  if (!t) return ''

  const span = Math.max(0, Date.now() - t)
  if (span < MINUTE_MS) return 'just now'
  if (span < HOUR_MS) return `${Math.floor(span / MINUTE_MS)}m ago`
  if (span < DAY_MS) return `${Math.floor(span / HOUR_MS)}h ago`
  return `${Math.floor(span / DAY_MS)}d ago`
}

export function timeWithDay(ts: number, day: Intl.DateTimeFormatOptions): string {
  const when = new Date(ts)
  const time = when.toLocaleTimeString([], CLOCK)
  if (when.toDateString() === new Date().toDateString()) return time
  return `${when.toLocaleDateString([], day)}, ${time}`
}

export function seconds(ms: number): string {
  return `${(ms / SECOND_MS).toFixed(1)}s`
}
