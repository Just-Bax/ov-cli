import { useEffect } from 'react'

export function useUnsavedWarning(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
}

export function UnsavedGuard({ dirty }: { dirty: boolean }) {
  useUnsavedWarning(dirty)
  return null
}
