import { useEffect, useState } from 'react'
import type { HealthMeta, HealthSection, HealthSections } from '@shared/types.ts'
import { api } from '@/lib/api'
import { DAY_MS, HOUR_MS, MINUTE_MS, SECOND_MS } from '@/lib/time'

export const RANGES = ['1h', '24h', '7d'] as const
export type Range = (typeof RANGES)[number]
export const RANGE_WORDS: Record<Range, string> = {
  '1h': 'hour',
  '24h': '24 hours',
  '7d': '7 days',
}

const SECTIONS: HealthSection[] = [
  'incidents',
  'maintenance',
  'monitors',
  'traffic',
  'servers',
  'database',
]

export type Slot<K extends HealthSection> =
  | { state: 'loading' }
  | { state: 'ready'; value: HealthSections[K] }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; error: string }

export type Slots = { [K in HealthSection]: Slot<K> }

const LOADING = Object.fromEntries(SECTIONS.map((s) => [s, { state: 'loading' }])) as Slots

export function useHealth(alias: string, range: Range, enabled: boolean, refresh: string) {
  const [meta, setMeta] = useState<HealthMeta>()
  const [metaError, setMetaError] = useState<string>()
  const [slots, setSlots] = useState<Slots>(LOADING)

  useEffect(() => {
    if (!enabled || !alias) return

    let alive = true
    setSlots(LOADING)
    setMetaError(undefined)

    const load = <K extends HealthSection>(section: K, to: number) =>
      api
        .healthSection(section, alias, range, to)
        .then((result) => {
          const slot: Slot<K> =
            'unavailable' in result
              ? { state: 'unavailable', reason: result.unavailable }
              : { state: 'ready', value: result as HealthSections[K] }
          if (alive) setSlots((s) => ({ ...s, [section]: slot }))
        })
        .catch((e: Error) => {
          if (alive) setSlots((s) => ({ ...s, [section]: { state: 'error', error: e.message } }))
        })

    api
      .healthMeta(alias, range)
      .then((m) => {
        if (!alive) return
        setMeta(m)
        for (const section of SECTIONS) void load(section, m.to)
      })
      .catch((e: Error) => alive && setMetaError(e.message))

    return () => {
      alive = false
    }
  }, [alias, range, enabled, refresh])

  const current = meta?.instance === alias && meta.range === range ? meta : undefined
  const busy = SECTIONS.some((s) => slots[s].state === 'loading')
  return { meta: current, metaError, slots, busy }
}

export function ready<K extends HealthSection>(slot: Slot<K>): HealthSections[K] | undefined {
  return slot.state === 'ready' ? slot.value : undefined
}

const THOUSAND = 1000
const MILLION = 1_000_000
const WHOLE_THOUSANDS_FROM = 10 * THOUSAND
const WHOLE_SECONDS_FROM_MS = 10 * SECOND_MS
const ONE_DECIMAL_BELOW = 10
const TWO_DECIMALS_BELOW = 100
const KIBI = 1024
const DAYS_FROM_HOURS = 48
const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

export function count(n: number): string {
  if (n >= MILLION) return `${(n / MILLION).toFixed(1)}M`
  if (n >= WHOLE_THOUSANDS_FROM) return `${Math.round(n / THOUSAND)}k`
  if (n >= THOUSAND) return `${(n / THOUSAND).toFixed(1)}k`
  return String(Math.round(n))
}

export function duration(ms: number): string {
  if (ms >= MINUTE_MS) return `${(ms / MINUTE_MS).toFixed(1)}m`
  if (ms >= SECOND_MS) return `${(ms / SECOND_MS).toFixed(ms >= WHOLE_SECONDS_FROM_MS ? 0 : 1)}s`
  return `${Math.round(ms)}ms`
}

function oneDecimalBelowTen(value: number): string {
  return value.toFixed(value >= ONE_DECIMAL_BELOW ? 0 : 1)
}

export function fmt(value: number, unit: string): string {
  if (unit === '%') return `${oneDecimalBelowTen(value)}%`
  if (unit !== 'B') return value >= TWO_DECIMALS_BELOW ? count(value) : value.toFixed(2)

  let v = value
  let i = 0
  while (v >= KIBI && i < BYTE_UNITS.length - 1) {
    v /= KIBI
    i++
  }

  return `${oneDecimalBelowTen(v)} ${BYTE_UNITS[i]}`
}

export function span(fromMs: number, toMs: number): string {
  const minutes = Math.max(1, Math.round((toMs - fromMs) / MINUTE_MS))
  if (minutes < HOUR_MS / MINUTE_MS) return `${minutes}m`
  const hours = Math.round((minutes * MINUTE_MS) / HOUR_MS)
  return hours < DAYS_FROM_HOURS ? `${hours}h` : `${Math.round((hours * HOUR_MS) / DAY_MS)}d`
}

export function utcMs(text: string): number {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text.replace(' ', 'T')}Z`).getTime()
}

export function clock(ms: number, range: Range): string {
  const d = new Date(ms)
  return range === '7d'
    ? d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export const total = (points: { v: number }[]) => points.reduce((sum, p) => sum + p.v, 0)
