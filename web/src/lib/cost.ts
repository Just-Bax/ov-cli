import type { CostTotal, CostUnit } from '@shared/types.ts'

const THOUSAND = 1000
const MILLION = 1_000_000
const SMALL_CREDITS = 10
const MEDIUM_CREDITS = 1000

const TOKEN_LABELS: Record<string, string> = {
  input: 'Input',
  cache_read: 'Cached input',
  cache_write: 'Cache write',
  output: 'Output',
}

export function tokenLabel(kind: string): string {
  return TOKEN_LABELS[kind] ?? kind.replace(/_/g, ' ')
}

export function formatCredits(credits: number): string {
  const digits = credits < SMALL_CREDITS ? 2 : credits < MEDIUM_CREDITS ? 1 : 0
  return credits.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatTokens(count: number): string {
  if (count >= MILLION) return `${(count / MILLION).toFixed(1)}M`
  if (count >= THOUSAND) return `${(count / THOUSAND).toFixed(1)}k`
  return String(count)
}

export function orderedTokens(tokens: Record<string, number>): [string, number][] {
  const known = Object.keys(TOKEN_LABELS)

  return Object.entries(tokens)
    .filter(([, count]) => count > 0)
    .sort(([a], [b]) => {
      const ia = known.indexOf(a)
      const ib = known.indexOf(b)
      return (ia < 0 ? known.length : ia) - (ib < 0 ? known.length : ib)
    })
}

function formatUsd(usd: number): string {
  return `$${usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const UNIT_FORMATS: Record<CostUnit, (value: number) => string> = {
  usd: formatUsd,
  credits: (value) => `${formatCredits(value)} credits`,
  tokens: (value) => `${formatTokens(value)} tokens`,
}

export function formatAmount(value: number, unit: CostUnit): string {
  return UNIT_FORMATS[unit](value)
}

export function formatCost(cost: CostTotal, unit: CostUnit): string {
  return formatAmount(cost.amount, unit)
}
