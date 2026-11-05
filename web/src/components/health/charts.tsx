import { useState } from 'react'
import type { HealthPoint } from '@shared/types.ts'
import { clock, type Range, whenOf } from './data'

const WIDTH = 1000
const TOP_PAD = 4
const BAR_GAP = 0.18
const BAR_RADIUS = 2
const LINE_WIDTH = 2
const DOT_RADIUS = 3
const TOOLTIP_FLIP = 0.62
const GRID_COLOR = '#eceff1'
const CURSOR_COLOR = '#90a4ae'
const LIMIT_COLOR = '#e46b00'
const LABEL_WIDTH = 96
const EVENT_LANE_HEIGHT = 12
const MIN_SPAN_PERCENT = 0.6
const AXIS_TICKS = [0, 0.5, 1]
const FULL_PERCENT = 100
const TYPICAL_PLOT_PX = 800
const BAR_OPACITY = 0.4
const HOVERED_BAR_OPACITY = 0.75
const LANE_LIMIT_OPACITY = 0.6
const METRIC_LIMIT_OPACITY = 0.7
const LIMIT_DASH = '4 4'
const CURSOR_DASH = '3 3'
const EVENT_DOT_PX = 8
const METRIC_HEIGHT = 44
const METRIC_FILL_OPACITY = 0.14

type Lane = {
  label: string
  color: string
  kind: 'bars' | 'line'
  points: HealthPoint[]
  format: (v: number) => string
  height: number
  limit?: number
}

export type Happening = {
  from: number
  to?: number
  color: string
  label: string
}

export type EventLane = { label: string; items: Happening[] }

function bucketsOf(from: number, to: number, interval: number) {
  const start = Math.floor(from / interval) * interval
  return { start, count: Math.max(1, Math.ceil((to - start) / interval)) }
}

function bucketize(points: HealthPoint[], start: number, count: number, interval: number) {
  const out: (number | null)[] = Array(count).fill(null)
  for (const p of points) {
    const i = Math.floor((p.t - start) / interval)
    if (i >= 0 && i < count) out[i] = Math.max(out[i] ?? 0, p.v)
  }

  return out
}

function y(v: number, max: number, height: number): number {
  return height - (v / max) * (height - TOP_PAD)
}

function linePaths(values: (number | null)[], max: number, height: number, slot: number) {
  const segments: string[] = []
  const singles: { x: number; y: number }[] = []
  let current: { x: number; y: number }[] = []

  const flush = () => {
    if (current.length === 1) singles.push(current[0])
    if (current.length > 1)
      segments.push(current.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' '))
    current = []
  }

  values.forEach((v, i) => {
    if (v === null) return flush()
    current.push({ x: i * slot + slot / 2, y: y(v, max, height) })
  })
  flush()

  return { segments, singles }
}

function LanePlot({
  lane,
  values,
  slot,
  at,
}: {
  lane: Lane
  values: (number | null)[]
  slot: number
  at: number
}) {
  const max = Math.max(...values.map((v) => v ?? 0), lane.limit ?? 0) || 1
  const { height } = lane
  const { segments, singles } = linePaths(values, max, height, slot)

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height}`}
      preserveAspectRatio="none"
      className="block w-full overflow-visible"
      style={{ height }}
    >
      <line
        x1={0}
        x2={WIDTH}
        y1={height}
        y2={height}
        stroke={GRID_COLOR}
        vectorEffect="non-scaling-stroke"
      />
      {lane.limit !== undefined && lane.limit <= max ? (
        <line
          x1={0}
          x2={WIDTH}
          y1={y(lane.limit, max, height)}
          y2={y(lane.limit, max, height)}
          stroke={LIMIT_COLOR}
          strokeDasharray={LIMIT_DASH}
          opacity={LANE_LIMIT_OPACITY}
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
      {lane.kind === 'bars'
        ? values.map((v, i) =>
            v ? (
              <rect
                key={i}
                x={i * slot + slot * BAR_GAP}
                y={y(v, max, height)}
                width={slot * (1 - BAR_GAP * 2)}
                height={height - y(v, max, height)}
                rx={BAR_RADIUS}
                fill={lane.color}
                opacity={at === -1 || at === i ? HOVERED_BAR_OPACITY : BAR_OPACITY}
              />
            ) : null,
          )
        : null}
      {lane.kind === 'line'
        ? segments.map((d, i) => (
            <path
              key={i}
              d={d}
              fill="none"
              stroke={lane.color}
              strokeWidth={LINE_WIDTH}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))
        : null}
      {lane.kind === 'line'
        ? singles.map((p, i) => (
            <ellipse
              key={i}
              cx={p.x}
              cy={p.y}
              rx={(DOT_RADIUS * WIDTH) / TYPICAL_PLOT_PX}
              ry={DOT_RADIUS}
              fill={lane.color}
            />
          ))
        : null}
      {at >= 0 ? (
        <line
          x1={at * slot + slot / 2}
          x2={at * slot + slot / 2}
          y1={0}
          y2={height}
          stroke={CURSOR_COLOR}
          strokeDasharray={CURSOR_DASH}
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
    </svg>
  )
}

function percentOf(t: number, from: number, to: number): number {
  return Math.min(FULL_PERCENT, Math.max(0, ((t - from) / (to - from)) * FULL_PERCENT))
}

function EventRow({ lane, from, to }: { lane: EventLane; from: number; to: number }) {
  const shown = lane.items.filter((i) => (i.to ?? i.from) >= from && i.from <= to)

  return (
    <div className="relative" style={{ height: EVENT_LANE_HEIGHT }}>
      <div className="bg-line absolute inset-x-0 top-1/2 h-px" />
      {shown.map((item, i) => {
        const left = percentOf(item.from, from, to)
        const width = item.to ? Math.max(MIN_SPAN_PERCENT, percentOf(item.to, from, to) - left) : 0

        return (
          <span
            key={i}
            title={item.label}
            className="absolute top-1/2 -translate-y-1/2 rounded-full ring-2 ring-white"
            style={{
              left: `${left}%`,
              width: width ? `${width}%` : EVENT_DOT_PX,
              height: EVENT_DOT_PX,
              marginLeft: width ? 0 : -EVENT_DOT_PX / 2,
              background: item.color,
            }}
          />
        )
      })}
    </div>
  )
}

export function Lanes({
  from,
  to,
  interval,
  range,
  lanes,
  events,
}: {
  from: number
  to: number
  interval: number
  range: Range
  lanes: Lane[]
  events: EventLane[]
}) {
  const [hover, setHover] = useState<number>()
  const { start, count } = bucketsOf(from, to, interval)
  const slot = WIDTH / count
  const values = lanes.map((l) => bucketize(l.points, start, count, interval))
  const at = hover ?? -1
  const bucketStart = start + at * interval
  const happening = events.flatMap((e) =>
    e.items.filter((i) => i.from < bucketStart + interval && (i.to ?? i.from) >= bucketStart),
  )

  return (
    <div className="relative">
      <div
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const x = e.clientX - r.left - LABEL_WIDTH
          setHover(
            x < 0
              ? undefined
              : Math.min(count - 1, Math.floor((x / (r.width - LABEL_WIDTH)) * count)),
          )
        }}
        onMouseLeave={() => setHover(undefined)}
        className="space-y-2"
      >
        {lanes.map((lane, k) => (
          <div key={lane.label} className="flex items-end">
            <div className="shrink-0 pr-3 pb-0.5" style={{ width: LABEL_WIDTH }}>
              <div className="text-muted flex items-center gap-1.5 text-[11.5px]">
                <span className="size-2 shrink-0 rounded-full" style={{ background: lane.color }} />
                {lane.label}
              </div>
              <div className="text-faint text-[10.5px] tabular-nums">
                max {lane.format(Math.max(0, ...values[k].map((v) => v ?? 0)))}
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <LanePlot lane={lane} values={values[k]} slot={slot} at={at} />
            </div>
          </div>
        ))}
        {events.map((lane) => (
          <div key={lane.label} className="flex items-center">
            <div
              className="text-muted shrink-0 truncate pr-3 text-[11.5px]"
              style={{ width: LABEL_WIDTH }}
            >
              {lane.label}
            </div>
            <div className="min-w-0 flex-1">
              <EventRow lane={lane} from={start} to={start + count * interval} />
            </div>
          </div>
        ))}
      </div>

      <div
        className="text-faint flex justify-between pt-1.5 text-[11px]"
        style={{ paddingLeft: LABEL_WIDTH }}
      >
        {AXIS_TICKS.map((f) => (
          <span key={f}>{clock(from + (to - from) * f, range)}</span>
        ))}
      </div>

      {at >= 0 ? (
        <div
          className="border-line pointer-events-none absolute top-0 z-10 w-max max-w-[300px] rounded-2xl border bg-white px-3 py-2 text-[11.5px] shadow-[0_6px_20px_rgba(38,50,56,0.14)]"
          style={{
            left: `calc(${LABEL_WIDTH}px + (100% - ${LABEL_WIDTH}px) * ${(at + 0.5) / count})`,
            transform: `translateX(${at > count * TOOLTIP_FLIP ? '-105%' : '5%'})`,
          }}
        >
          <div className="text-fg font-medium">
            {clock(bucketStart, range)} - {clock(bucketStart + interval, range)}
          </div>
          {lanes.map((lane, k) => (
            <div key={lane.label} className="text-muted mt-0.5 flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: lane.color }} />
              {lane.label}
              <span className="text-fg ml-auto pl-3 font-medium tabular-nums">
                {values[k][at] === null ? 'no data' : lane.format(values[k][at]!)}
              </span>
            </div>
          ))}
          {happening.map((h, i) => (
            <div key={i} className="text-text mt-1 flex items-start gap-1.5">
              <span className="mt-1 size-2 shrink-0 rounded-full" style={{ background: h.color }} />
              <span className="line-clamp-2">{h.label}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function MetricChart({
  points,
  color,
  limit,
  ceiling,
  format,
}: {
  points: HealthPoint[]
  color: string
  limit?: number
  ceiling?: number
  format: (v: number) => string
}) {
  const [hover, setHover] = useState<number>()
  if (points.length < 2) return <div style={{ height: METRIC_HEIGHT }} />

  const first = points[0].t
  const span = points[points.length - 1].t - first || 1
  const max = ceiling ?? (Math.max(...points.map((p) => p.v), limit ?? 0) || 1)
  const at = (p: HealthPoint) =>
    `${(((p.t - first) / span) * WIDTH).toFixed(1)},${y(Math.min(p.v, max), max, METRIC_HEIGHT).toFixed(1)}`
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${at(p)}`).join(' ')
  const area = `${line} L${WIDTH},${METRIC_HEIGHT} L0,${METRIC_HEIGHT} Z`
  const hovered = hover === undefined ? undefined : points[hover]

  return (
    <div
      className="relative"
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        const t = first + ((e.clientX - r.left) / r.width) * span
        let best = 0
        points.forEach((p, i) => {
          if (Math.abs(p.t - t) < Math.abs(points[best].t - t)) best = i
        })
        setHover(best)
      }}
      onMouseLeave={() => setHover(undefined)}
    >
      <svg
        viewBox={`0 0 ${WIDTH} ${METRIC_HEIGHT}`}
        preserveAspectRatio="none"
        className="block w-full overflow-visible"
        style={{ height: METRIC_HEIGHT }}
      >
        <path d={area} fill={color} opacity={METRIC_FILL_OPACITY} />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth={LINE_WIDTH}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {limit !== undefined && limit <= max ? (
          <line
            x1={0}
            x2={WIDTH}
            y1={y(limit, max, METRIC_HEIGHT)}
            y2={y(limit, max, METRIC_HEIGHT)}
            stroke={LIMIT_COLOR}
            strokeDasharray={LIMIT_DASH}
            opacity={METRIC_LIMIT_OPACITY}
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
        {hovered ? (
          <line
            x1={((hovered.t - first) / span) * WIDTH}
            x2={((hovered.t - first) / span) * WIDTH}
            y1={0}
            y2={METRIC_HEIGHT}
            stroke={CURSOR_COLOR}
            strokeDasharray={CURSOR_DASH}
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
      {hovered ? (
        <div
          className="border-line pointer-events-none absolute -top-7 z-10 rounded-full border bg-white px-2 py-0.5 text-[11px] whitespace-nowrap shadow-sm"
          style={{
            left: `${((hovered.t - first) / span) * FULL_PERCENT}%`,
            transform: `translateX(${(hovered.t - first) / span > TOOLTIP_FLIP ? '-100%' : '0'})`,
          }}
        >
          <span className="text-fg font-medium tabular-nums">{format(hovered.v)}</span>
          <span className="text-faint ml-1.5">{whenOf(hovered.t)}</span>
        </div>
      ) : null}
    </div>
  )
}
