const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS
const WEEK_MS = 7 * DAY_MS

export function shortSpan(ms: number): string {
  const span = Math.max(0, ms)
  if (span < MINUTE_MS) return 'now'
  if (span < HOUR_MS) return `${Math.round(span / MINUTE_MS)}m`
  if (span < DAY_MS) return `${Math.round(span / HOUR_MS)}h`
  if (span < WEEK_MS) return `${Math.round(span / DAY_MS)}d`
  return `${Math.round(span / WEEK_MS)}w`
}
