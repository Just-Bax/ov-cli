import { useEffect, useRef, useState } from 'react'
import { Card, Skeleton } from '@/components/common/ui'
import { cn } from '@/lib/cn'

const SKELETON_DELAY_MS = 300
const SKELETON_MIN_MS = 500
const CODE_WIDTHS = ['w-1/3', 'w-2/3', 'w-1/2', 'w-5/6', 'w-3/5', 'w-1/4', 'w-3/4', 'w-2/5']
const TREE_WIDTHS = ['w-32', 'w-40', 'w-28', 'w-44', 'w-36', 'w-24']
const TREE_PADDING_PX = 10
const CODE_INDENT_PX = 14
const CODE_INDENT_LEVELS = 4
const CODE_LINES = 18

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

function TreeRowsSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-1 py-1">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="flex h-7 items-center gap-2"
          style={{ paddingLeft: TREE_PADDING_PX }}
        >
          <Skeleton className="size-3.5 shrink-0 rounded" />
          <Skeleton className={cn('h-2.5', TREE_WIDTHS[i % TREE_WIDTHS.length])} />
        </div>
      ))}
    </div>
  )
}

export function CodeSkeleton() {
  return (
    <div className="space-y-2.5 p-5">
      {Array.from({ length: CODE_LINES }, (_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-2.5 w-5 shrink-0" />
          <Skeleton
            className={cn('h-2.5', CODE_WIDTHS[i % CODE_WIDTHS.length])}
            style={{ marginLeft: (i % CODE_INDENT_LEVELS) * CODE_INDENT_PX }}
          />
        </div>
      ))}
    </div>
  )
}

export function ActionsSkeleton({ widths }: { widths: string[] }) {
  return widths.map((width) => <Skeleton key={width} className={cn('h-9 rounded-full', width)} />)
}

export function ComposerSkeleton() {
  return (
    <div className="px-6 pt-1 pb-4">
      <div className="border-line-strong/60 mx-auto flex h-[104px] max-w-[860px] flex-col justify-between rounded-[26px] border bg-white px-2.5 pt-4 pb-2.5">
        <Skeleton className="ml-1.5 h-3 w-56" />
        <div className="flex items-center gap-1.5">
          <Skeleton className="size-8 rounded-full" />
          <Skeleton className="h-8 w-32 rounded-full" />
          <Skeleton className="ml-auto size-8 rounded-full" />
        </div>
      </div>
    </div>
  )
}

export function HomeSkeleton() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-[760px]">
        <Skeleton className="mx-auto mb-6 h-7 w-[440px] max-w-full rounded-full" />
        <div className="border-line-strong/60 rounded-[28px] border bg-white">
          <div className="min-h-[72px] px-4 pt-4">
            <Skeleton className="h-3 w-2/3" />
          </div>
          <div className="flex items-center gap-2 px-3 pb-3">
            <Skeleton className="size-8 rounded-full" />
            <Skeleton className="h-8 w-32 rounded-full" />
            <Skeleton className="h-8 w-28 rounded-full" />
            <Skeleton className="ml-auto size-8 rounded-full" />
          </div>
        </div>
        <Skeleton className="mx-auto mt-3 h-2.5 w-80" />
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
