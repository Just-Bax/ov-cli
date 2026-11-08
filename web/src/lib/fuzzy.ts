const TIER = 1000
const SECONDARY_TIERS = 5
const BOUNDARY = /[\s\-_/.:]/

function subsequenceGaps(text: string, query: string): number | undefined {
  let gaps = 0
  let at = 0
  for (const char of query) {
    const found = text.indexOf(char, at)
    if (found < 0) return undefined
    gaps += found - at
    at = found + 1
  }

  return gaps
}

function atBoundary(text: string, query: string): boolean {
  let at = text.indexOf(query)
  while (at > 0) {
    if (BOUNDARY.test(text[at - 1])) return true
    at = text.indexOf(query, at + 1)
  }

  return at === 0
}

export function matchScore(text: string, query: string): number | undefined {
  const t = text.toLowerCase()
  const q = query.toLowerCase()
  if (!q) return 0
  if (t === q) return 0
  if (t.startsWith(q)) return TIER + t.length
  if (atBoundary(t, q)) return 2 * TIER + t.length
  if (t.includes(q)) return 3 * TIER + t.length

  const gaps = subsequenceGaps(t, q)
  return gaps === undefined ? undefined : 4 * TIER + gaps * 10 + t.length
}

export function rank<T>(
  items: T[],
  query: string,
  fields: (item: T) => [string, string?],
  limit: number,
): T[] {
  if (!query) return items.slice(0, limit)

  const scored: [number, T][] = []
  for (const item of items) {
    const [primary, secondary] = fields(item)
    const main = matchScore(primary, query)
    const extra = secondary ? matchScore(secondary, query) : undefined
    const score = main ?? (extra === undefined ? undefined : extra + SECONDARY_TIERS * TIER)
    if (score !== undefined) scored.push([score, item])
  }

  return scored
    .sort((a, b) => a[0] - b[0])
    .slice(0, limit)
    .map(([, item]) => item)
}
