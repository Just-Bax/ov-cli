import type { RunState } from './types.ts'

/** Minutes the agent estimated it saved on this run; a run rated wrong saved nothing. */
export function savedMinutes(state: RunState): number {
  if (state.feedback?.rating === 'wrong') return 0
  return Math.max(0, Math.round(state.outcome?.timeSaved?.minutes ?? 0))
}

export function formatMinutes(min: number): string {
  if (min < 60) return `${min}m`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h}h ${m}m` : `${h}h`
}
