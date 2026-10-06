import { useEffect, useRef, useState } from 'react'
import { Card, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'

export const SKELETON_DELAY_MS = 300
const SKELETON_MIN_MS = 500
const CODE_WIDTHS = ['w-1/3', 'w-2/3', 'w-1/2', 'w-5/6', 'w-3/5', 'w-1/4', 'w-3/4', 'w-2/5']
const TREE_WIDTHS = ['w-32', 'w-40', 'w-28', 'w-44', 'w-36', 'w-24']

export function useSkeleton(loading: boolean): boolean {
  const started = useRef<number | undefined>(undefined)
  const [holding, setHolding] = useState(false)

  useEffect(() => {
    if (loading) {
      started.current ??= Date.now()
      return
    }
    if (started.current === undefined) return

    const visibleFor = Date.now() - started.current - SKELETON_DELAY_MS
    started.current = undefined
    if (visibleFor <= 0 || visibleFor >= SKELETON_MIN_MS) return

    setHolding(true)
    const timer = setTimeout(() => setHolding(false), SKELETON_MIN_MS - visibleFor)
    return () => clearTimeout(timer)
  }, [loading])

  return loading || holding
}

export function TreeRowsSkeleton({ rows = 10, indent = 0 }: { rows?: number; indent?: number }) {
  return (
    <div className="space-y-1 py-1">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-7 items-center gap-2" style={{ paddingLeft: indent + 10 }}>
          <Skeleton className="size-3.5 shrink-0 rounded" />
          <Skeleton className={cn('h-2.5', TREE_WIDTHS[i % TREE_WIDTHS.length])} />
        </div>
      ))}
    </div>
  )
}

export function CodeSkeleton({ lines = 18 }: { lines?: number }) {
  return (
    <div className="space-y-2.5 p-5">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-2.5 w-5 shrink-0" />
          <Skeleton
            className={cn('h-2.5', CODE_WIDTHS[i % CODE_WIDTHS.length])}
            style={{ marginLeft: (i % 4) * 14 }}
          />
        </div>
      ))}
    </div>
  )
}

export function ExplorerSkeleton() {
  return (
    <div className="flex h-full min-h-[480px]">
      <div className="border-line-strong/60 w-[300px] shrink-0 space-y-2 border-r p-3">
        <Skeleton className="h-9 w-full rounded-full" />
        <TreeRowsSkeleton rows={14} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="border-line flex h-12 items-center gap-2 border-b px-3">
          <Skeleton className="h-7 w-36 rounded-full" />
          <Skeleton className="h-7 w-28 rounded-full" />
        </div>
        <CodeSkeleton />
      </div>
      <div className="border-line-strong/60 w-[340px] shrink-0 space-y-3 border-l p-4">
        <div className="flex items-center gap-3">
          <Skeleton className="size-8 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-40" />
            <Skeleton className="h-2.5 w-24" />
          </div>
        </div>
        <Skeleton className="h-20 w-full rounded-2xl" />
        <div className="flex gap-1.5">
          <Skeleton className="h-8 flex-1 rounded-full" />
          <Skeleton className="size-8 rounded-full" />
          <Skeleton className="size-8 rounded-full" />
        </div>
        <TreeRowsSkeleton rows={6} />
      </div>
    </div>
  )
}

export function MapSkeleton() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-line flex h-14 shrink-0 items-center gap-2 border-b bg-white px-4">
        <Skeleton className="h-9 w-[320px] rounded-full" />
        <Skeleton className="h-9 w-36 rounded-full" />
      </div>
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-[1240px]">
          <Skeleton className="mx-auto h-4 w-48" />
          <Skeleton className="mx-auto mt-2 mb-6 h-3 w-96" />
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Card key={i} className="space-y-3 p-4">
                <Skeleton className="h-3.5 w-36" />
                <Skeleton className="h-2.5 w-28" />
                <TreeRowsSkeleton rows={6} />
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
