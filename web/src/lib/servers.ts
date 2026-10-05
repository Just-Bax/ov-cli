// Keep in sync with hosts_in, scope_of and role_of in datadog.py.
export function hostsIn(scope: string): string[] | null {
  const text = scope.trim()
  const many = /^host:\(([^()]+)\)$/.exec(text)
  if (many)
    return many[1]
      .split(' OR ')
      .map((h) => h.trim())
      .filter(Boolean)
  const one = /^host:([^\s*()]+)$/.exec(text)
  return one ? [one[1]] : null
}

export function scopeOf(hosts: string[]): string {
  const list = [...new Set(hosts.map((h) => h.trim()).filter(Boolean))].sort()
  if (!list.length) return ''
  return list.length === 1 ? `host:${list[0]}` : `host:(${list.join(' OR ')})`
}

/** The leading words of the machine's own name: web01 -> web, db-3f9a -> db. */
export function roleOf(host: string): string {
  const first = host.split('.')[0].toLowerCase()
  const words: string[] = []
  for (const part of first.split(/[-_]/)) {
    if (/^[a-z]+$/.test(part)) {
      words.push(part)
      continue
    }
    const lead = /^[a-z]*/.exec(part)?.[0] ?? ''
    if (lead && !words.length) words.push(lead)
    break
  }
  return words.join('-') || first
}

export function shortHost(host: string): string {
  return host.split('.')[0]
}
