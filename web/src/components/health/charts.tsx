import { useState } from 'react'
import type { HealthPoint } from '@shared/types.ts'
import { cn } from '@/lib/cn'
import { clock, type Range } from './data'

const BUCKETS = 48
const WIDTH = 1000
const HEIGHT = 170
const TOP_PAD = 10
const LANE_HEIGHT = 26
const DOT_MIN = 4
const DOT_MAX = 8
const TOOLTIP_TITLES = 3
const TOOLTIP_FLIP = 0.65
const GRID_LINES = [0.25, 0.5, 0.75]
const SPARK_WIDTH = 120
const SPARK_HEIGHT = 28

type Series = {
  label: string
  color: string
  points: HealthPoint[]
  combine: 'sum' | 'max'
  format: (v: number) => string
}

export type Lane = { label: string; color: string; items: { t: number; title: string }[] }

function bucketize(points: HealthPoint[], from: number, width: number, combine: Series['combine']) {
  const out: (number | null)[] = Array(BUCKETS).fill(null)
  for (const p of points) {
    const i = Math.floor((p.t - from) / width)
    if (i < 0 || i >= BUCKETS) continue
    const prev = out[i] ?? 0
    out[i] = combine === 'sum' ? prev + p.v : Math.max(prev, p.v)
  }
  return out
}

function linePath(values: (number | null)[], max: number) {
  const slot = WIDTH / BUCKETS
  const y = (v: number) => HEIGHT - 4 - (v / max) * (HEIGHT - TOP_PAD - 4)
  let path = ''
  let pen = false
  values.forEach((v, i) => {
    if (v === null) {
      pen = false
      return
    }
    path += `${pen ? 'L' : 'M'}${(i * slot + slot / 2).toFixed(1)},${y(v).toFixed(1)} `
    pen = true
  })
  return path
}

export function Timeline({
  from,
  to,
  range,
  bars,
  lines,
  lanes,
}: {
  from: number
  to: number
  range: Range
  bars?: Series
  lines: Series[]
  lanes: Lane[]
}) {
  const [hover, setHover] = useState<number>()
  const width = (to - from) / BUCKETS
  const slot = WIDTH / BUCKETS
  const barValues = bars ? bucketize(bars.points, from, width, bars.combine) : []
  const barMax = Math.max(1, ...barValues.map((v) => v ?? 0))
  const lineValues = lines.map((l) => bucketize(l.points, from, width, l.combine))
  const laneBuckets = lanes.map((lane) => {
    const buckets: Lane['items'][] = Array.from({ length: BUCKETS }, () => [])
    for (const item of lane.items) {
      const i = Math.floor((item.t - from) / width)
      if (i >= 0 && i < BUCKETS) buckets[i].push(item)
    }
    return buckets
  })

  const at = hover ?? -1
  const startOf = (i: number) => from + i * width

  return (
    <div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 pb-2 text-[11.5px]">
        {[...(bars ? [bars] : []), ...lines].map((s) => (
          <span key={s.label} className="text-muted inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <div className="pl-20">
        <div
          className="relative"
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            setHover(
              Math.min(
                BUCKETS - 1,
                Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * BUCKETS)),
              ),
            )
          }}
          onMouseLeave={() => setHover(undefined)}
        >
          {bars ? (
            <span className="text-faint absolute top-0 -left-20 w-20 truncate pr-2 text-[10.5px]">
              {bars.format(barMax)}
            </span>
          ) : null}
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            preserveAspectRatio="none"
            className="block w-full"
            style={{ height: HEIGHT }}
          >
            {GRID_LINES.map((f) => (
              <line
                key={f}
                x1={0}
                x2={WIDTH}
                y1={HEIGHT * f}
                y2={HEIGHT * f}
                stroke="#eceff1"
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {bars
              ? barValues.map((v, i) => {
                  const top = HEIGHT - 4 - ((v ?? 0) / barMax) * (HEIGHT - TOP_PAD - 4)
                  return (
                    <rect
                      key={i}
                      x={i * slot + 2}
                      y={top}
                      width={slot - 4}
                      height={Math.max(0, HEIGHT - 4 - top)}
                      rx={3}
                      fill={bars.color}
                      opacity={at === -1 || at === i ? 0.55 : 0.25}
                    />
                  )
                })
              : null}
            {lines.map((l, k) => (
              <path
                key={l.label}
                d={linePath(lineValues[k], Math.max(1, ...lineValues[k].map((v) => v ?? 0)))}
                fill="none"
                stroke={l.color}
                strokeWidth={2}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {at >= 0 ? (
              <line
                x1={at * slot + slot / 2}
                x2={at * slot + slot / 2}
                y1={0}
                y2={HEIGHT}
                stroke="#90a4ae"
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </svg>

          <div className="border-line mt-1 border-t">
            {lanes.map((lane, k) => (
              <div
                key={lane.label}
                className="relative flex items-center"
                style={{ height: LANE_HEIGHT }}
              >
                <span className="text-faint absolute -left-20 w-20 truncate pr-2 text-[10.5px] font-medium">
                  {lane.label}
                </span>
                {laneBuckets[k].map((items, i) =>
                  items.length ? (
                    <span
                      key={i}
                      className="absolute -translate-x-1/2 rounded-full ring-2 ring-white"
                      style={{
                        left: `${((i + 0.5) / BUCKETS) * 100}%`,
                        background: lane.color,
                        width: Math.min(DOT_MAX, DOT_MIN + items.length) * 2,
                        height: Math.min(DOT_MAX, DOT_MIN + items.length) * 2,
                        opacity: at === -1 || at === i ? 1 : 0.55,
                      }}
                    />
                  ) : null,
                )}
              </div>
            ))}
          </div>

          {at >= 0 ? (
            <div
              className="border-line pointer-events-none absolute top-1 z-10 max-w-[320px] rounded-2xl border bg-white px-3 py-2 text-[11.5px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
              style={{
                left: `${((at + 0.5) / BUCKETS) * 100}%`,
                transform: `translateX(${at > BUCKETS * TOOLTIP_FLIP ? '-105%' : '5%'})`,
              }}
            >
              <div className="text-fg font-medium">
                {clock(startOf(at), range)} - {clock(startOf(at + 1), range)}
              </div>
              {[
                ...(bars ? [{ s: bars, v: barValues[at] }] : []),
                ...lines.map((s, k) => ({ s, v: lineValues[k][at] })),
              ].map(({ s, v }) => (
                <div
                  key={s.label}
                  className="text-muted mt-0.5 flex items-center gap-1.5 whitespace-nowrap"
                >
                  <span className="size-2 rounded-full" style={{ background: s.color }} />
                  {s.label} {v === null ? '-' : s.format(v)}
                </div>
              ))}
              {lanes.map((lane, k) =>
                laneBuckets[k][at].length ? (
                  <div key={lane.label} className="mt-1.5">
                    <div className="text-fg flex items-center gap-1.5 font-medium">
                      <span className="size-2 rounded-full" style={{ background: lane.color }} />
                      {laneBuckets[k][at].length} {lane.label.toLowerCase()}
                    </div>
                    {laneBuckets[k][at].slice(0, TOOLTIP_TITLES).map((item, i) => (
                      <div key={i} className="text-muted truncate pl-3.5">
                        {item.title}
                      </div>
                    ))}
                  </div>
                ) : null,
              )}
            </div>
          ) : null}
        </div>
      </div>
      <div className="text-faint flex justify-between pt-1.5 pl-20 text-[11px]">
        <span>{clock(from, range)}</span>
        <span>{clock(from + (to - from) / 2, range)}</span>
        <span>{clock(to, range)}</span>
      </div>
    </div>
  )
}

export function Sparkline({
  points,
  color,
  className,
}: {
  points: HealthPoint[]
  color: string
  className?: string
}) {
  if (points.length < 2) return <div className={className} style={{ height: SPARK_HEIGHT }} />

  const ys = points.map((p) => p.v)
  const [lo, hi] = [Math.min(...ys), Math.max(...ys)]
  const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1
  const [y0, y1] = [lo - pad, hi + pad]
  const x = (i: number) => (i / (points.length - 1)) * SPARK_WIDTH
  const y = (v: number) => SPARK_HEIGHT - ((v - y0) / (y1 - y0)) * SPARK_HEIGHT
  const line = points
    .map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`)
    .join(' ')

  return (
    <svg
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      preserveAspectRatio="none"
      className={cn('block w-full', className)}
      style={{ height: SPARK_HEIGHT }}
    >
      <path
        d={`${line} L${SPARK_WIDTH},${SPARK_HEIGHT} L0,${SPARK_HEIGHT} Z`}
        fill={color}
        opacity={0.1}
      />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
