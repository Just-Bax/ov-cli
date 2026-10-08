const PREFETCH_TTL_MS = 30_000
const MAX_ENTRIES = 3

type Entry = { promise: Promise<unknown>; timer: ReturnType<typeof setTimeout> }

const slots = new Map<string, Map<string, Entry>>()

function drop(name: string, key: string) {
  const slot = slots.get(name)
  const entry = slot?.get(key)
  if (!slot || !entry) return
  clearTimeout(entry.timer)
  slot.delete(key)
}

export function prefetch<T>(name: string, key: string, load: () => Promise<T>): void {
  const slot = slots.get(name) ?? new Map<string, Entry>()
  slots.set(name, slot)
  if (slot.has(key)) return

  const oldest = slot.keys().next().value
  if (slot.size >= MAX_ENTRIES && oldest !== undefined) drop(name, oldest)

  const promise = load()
  promise.catch(() => {
    if (slot.get(key)?.promise === promise) drop(name, key)
  })
  slot.set(key, { promise, timer: setTimeout(() => drop(name, key), PREFETCH_TTL_MS) })
}

export function take<T>(name: string, key: string, load: () => Promise<T>): Promise<T> {
  const entry = slots.get(name)?.get(key)
  if (!entry) return load()
  drop(name, key)
  return entry.promise as Promise<T>
}
