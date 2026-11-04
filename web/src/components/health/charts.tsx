import { useState } from 'react'
import type { HealthPoint } from '@shared/types.ts'
import { clock, type Range } from './data'

const BUCKETS = 48
const WIDTH = 1000
const HEIGHT = 170
const TOP_PAD = 10
const TOOLTIP_FLIP = 0.65
const GRID_LINES = [0.25, 0.5, 0.75]
const BOTTOM_PAD = 4
const BAR_GAP = 2
const GRID_COLOR = '#eceff1'
const CURSOR_COLOR = '#90a4ae'
const BAR_RADIUS = 3
const BAR_OPACITY = 0.55
const DIMMED_BAR_OPACITY = 0.25
const LINE_WIDTH = 2

type Series = {
  label: string
  color: string
  points: HealthPoint[]
  combine: 'sum' | 'max'
  format: (v: number) => string
}

function bucketOf(t: number, from: number, width: number): number | undefined {
  const i = Math.floor((t - from) / width)
  return i >= 0 && i < BUCKETS ? i : undefined
}

function bucketize(points: HealthPoint[], from: number, width: number, combine: Series['combine']) {
  const out: (number | null)[] = Array(BUCKETS).fill(null)
  for (const p of points) {
    const i = bucketOf(p.t, from, width)
    if (i === undefined) continue

    const prev = out[i] ?? 0
    out[i] = combine === 'sum' ? prev + p.v : Math.max(prev, p.v)
  }

  return out
}

function plotY(v: number, max: number): number {
  return HEIGHT - BOTTOM_PAD - (v / max) * (HEIGHT - TOP_PAD - BOTTOM_PAD)
}

function linePath(values: (number | null)[], max: number) {
  const slot = WIDTH / BUCKETS
  let path = ''
  let pen = false
  values.forEach((v, i) => {
    if (v === null) {
      pen = false
      return
    }
    path += `${pen ? 'L' : 'M'}${(i * slot + slot / 2).toFixed(1)},${plotY(v, max).toFixed(1)} `
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
}: {
  from: number
  to: number
  range: Range
  bars?: Series
  lines: Series[]
}) {
  const [hover, setHover] = useState<number>()
  const width = (to - from) / BUCKETS
  const slot = WIDTH / BUCKETS
  const barValues = bars ? bucketize(bars.points, from, width, bars.combine) : []
  const barMax = Math.max(1, ...barValues.map((v) => v ?? 0))
  const lineValues = lines.map((l) => bucketize(l.points, from, width, l.combine))

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
                stroke={GRID_COLOR}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {bars
              ? barValues.map((v, i) => {
                  const top = plotY(v ?? 0, barMax)
                  return (
                    <rect
                      key={i}
                      x={i * slot + BAR_GAP}
                      y={top}
                      width={slot - BAR_GAP * 2}
                      height={Math.max(0, HEIGHT - BOTTOM_PAD - top)}
                      rx={BAR_RADIUS}
                      fill={bars.color}
                      opacity={at === -1 || at === i ? BAR_OPACITY : DIMMED_BAR_OPACITY}
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
                strokeWidth={LINE_WIDTH}
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
                stroke={CURSOR_COLOR}
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </svg>

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
