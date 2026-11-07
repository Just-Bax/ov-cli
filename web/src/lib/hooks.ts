import {
  type DependencyList,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { reportError } from '@/components/common/Toasts'

export function useClickOutside(
  inside: RefObject<Element | null>[],
  onOutside: () => void,
  active: boolean,
): void {
  const handler = useRef(onOutside)
  handler.current = onOutside

  useEffect(() => {
    if (!active) return
    const onDown = (e: MouseEvent) => {
      if (!inside.some((ref) => ref.current?.contains(e.target as Node))) handler.current()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [active])
}

export function useWindowEvent<K extends string>(
  name: K,
  handler: (e: K extends keyof WindowEventMap ? WindowEventMap[K] : Event) => void,
): void {
  const latest = useRef(handler)
  latest.current = handler

  useEffect(() => {
    const listen = (e: Event) => latest.current(e as Parameters<typeof handler>[0])
    window.addEventListener(name, listen)
    return () => window.removeEventListener(name, listen)
  }, [name])
}

export function useObjectUrls(files: File[]): Map<File, string> {
  const [urls, setUrls] = useState(() => new Map<File, string>())

  useEffect(() => {
    const next = new Map(files.map((file) => [file, URL.createObjectURL(file)]))
    setUrls(next)
    return () => next.forEach((url) => URL.revokeObjectURL(url))
  }, [files])

  return urls
}

export function useActiveIntoView(list: RefObject<HTMLElement | null>, active: number): void {
  useEffect(() => {
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])
}

export function useEnterTransition(key: unknown): boolean {
  const [shown, setShown] = useState(false)

  useEffect(() => {
    setShown(false)
    if (!key) return
    const frame = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(frame)
  }, [key])

  return shown
}

export function useLoad<T>(load: () => Promise<T>, deps: DependencyList) {
  const [value, setValue] = useState<T>()
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let alive = true
    setLoading(true)
    load()
      .then(
        (next) => alive && setValue(next),
        (e: unknown) => alive && reportError(e),
      )
      .finally(() => alive && setLoading(false))

    return () => {
      alive = false
    }
  }, [...deps, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { value, setValue, loading, reload }
}

export function usePresence<T>(value: T | undefined, exitMs: number) {
  const [kept, setKept] = useState(value)

  useEffect(() => {
    if (value !== undefined) {
      setKept(value)
      return
    }

    const timer = setTimeout(() => setKept(undefined), exitMs)
    return () => clearTimeout(timer)
  }, [value, exitMs])

  return { shown: value ?? kept, leaving: value === undefined && kept !== undefined }
}
