import {
  Check as CheckIcon,
  Warning as ExclamationTriangleIcon,
  Copy as Square2StackIcon,
} from '@phosphor-icons/react'
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  memo,
  useMemo,
} from 'react'
import type { MessageLinks } from '@shared/types.ts'
import type { Sparkle as SparklesIcon } from '@phosphor-icons/react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Dropdown } from '@/components/common/Dropdown'
import { reportError } from '@/components/common/Toasts'
import { cn } from '@/lib/cn'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const COPIED_FEEDBACK_MS = 1400

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-brand text-on-brand hover:bg-brand-strong disabled:bg-line-strong disabled:text-white',
  secondary: 'bg-brand-soft text-brand hover:bg-brand-chip disabled:bg-raised disabled:text-faint',
  ghost: 'text-text hover:bg-black/[0.06] disabled:text-faint',
  danger: 'text-danger hover:bg-danger-soft',
}

const SIZES: Record<Size, string> = {
  sm: 'h-7 gap-1 rounded-full px-3 text-[12px]',
  md: 'h-8 gap-1.5 rounded-full px-3.5 text-[12.5px]',
  lg: 'h-10 gap-2 rounded-full px-5 text-[13px]',
}

export type Icon = typeof SparklesIcon

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  ref?: React.Ref<HTMLButtonElement>
}) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-colors select-none disabled:pointer-events-none [&_svg]:shrink-0',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  )
}

export function IconButton({
  label,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'text-muted hover:bg-raised hover:text-fg inline-flex size-8 shrink-0 items-center justify-center rounded-full transition-colors disabled:opacity-40',
        className,
      )}
      {...props}
    />
  )
}

export type Tone = 'neutral' | 'brand' | 'ok' | 'warn' | 'danger'

const TONES: Record<Tone, string> = {
  neutral: 'bg-canvas text-text',
  brand: 'bg-brand-chip text-brand-strong',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  danger: 'bg-danger-soft text-danger',
}

export function Chip({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: Tone
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex h-[22px] shrink-0 items-center gap-1 rounded-full px-2.5 text-[11.5px] font-medium whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 50 50"
      className={cn('ov-spinner size-4 shrink-0', className)}
      aria-label="Loading"
    >
      <circle
        cx="25"
        cy="25"
        r="20"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="5"
        style={{ animation: 'none', strokeDasharray: 'none' }}
      />
      <circle
        cx="25"
        cy="25"
        r="20"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div className={cn('skeleton h-3', className)} style={style} />
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  const widths = ['w-11/12', 'w-full', 'w-4/5', 'w-2/3', 'w-5/6']

  return (
    <div className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={i === lines - 1 ? 'w-1/2' : widths[i % widths.length]} />
      ))}
    </div>
  )
}

type SegmentOption<T> = { value: T; label: ReactNode; title?: string }

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
  className,
}: {
  value: T
  options: SegmentOption<T>[]
  onChange: (value: T) => void
  label: string
  className?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn('bg-raised flex rounded-full p-1', className)}
    >
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cn(
            'h-7 min-w-11 flex-1 rounded-full px-3 text-[12.5px] font-medium whitespace-nowrap transition-colors',
            o.value === value ? 'text-fg bg-white shadow-sm' : 'text-muted hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn('border-line-strong/70 bg-panel rounded-2xl border', className)}>
      {children}
    </div>
  )
}

export function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  const copy = (text: string) =>
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS)
    }, reportError)

  return [copied, copy]
}

export function CopyButton({
  text,
  label = 'Copy',
  variant = 'secondary',
}: {
  text: string
  label?: string
  variant?: Variant
}) {
  const [copied, copy] = useCopy()

  return (
    <Button variant={variant} size="sm" onClick={() => copy(text)}>
      {copied ? <CheckIcon className="size-3.5" /> : <Square2StackIcon className="size-3.5" />}
      {copied ? 'Copied' : label}
    </Button>
  )
}

const FIELD =
  'border-line-strong bg-panel placeholder:text-faint focus:border-brand w-full border outline-none'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input className={cn(FIELD, 'h-9 rounded-full px-3.5 text-[13px]', className)} {...props} />
  )
}

export function Textarea({
  className,
  fill = false,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { fill?: boolean }) {
  return (
    <textarea
      className={cn(
        FIELD,
        'scrollbar-thin rounded-2xl px-3.5 py-2.5 text-[13px]',
        fill ? 'min-h-0 resize-none' : 'min-h-24 resize-y',
        className,
      )}
      {...props}
    />
  )
}

export function Select({
  value,
  onChange,
  options,
  className,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string; hint?: string }[]
  className?: string
  placeholder?: string
}) {
  return (
    <Dropdown
      value={value}
      onChange={onChange}
      options={options}
      placeholder={placeholder}
      variant="field"
      className={className}
    />
  )
}

const REMARK_PLUGINS = [remarkGfm]
const MARKDOWN_COMPONENTS: Components = {
  a: ({ node: _node, ...p }) => <a {...p} target="_blank" rel="noreferrer" />,
}

const CODE_SPANS = /(```[\s\S]*?```|`[^`\n]*`)/
const UNVERIFIED_TITLE =
  "This ID did not show up in the agent's tool results. Check it before relying on the link."

function escaped(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const mentionPatterns = new WeakMap<MessageLinks, { pattern: RegExp; urls: Map<string, string> }>()

function mentionPattern(links: MessageLinks) {
  const found = mentionPatterns.get(links)
  if (found) return found

  const alternatives = links.mentions.map((m) => escaped(m.text)).join('|')
  const made = {
    pattern: new RegExp(`(?<![\\[\\w/=])(${alternatives})(?![\\w\\]])`, 'g'),
    urls: new Map(links.mentions.map((m) => [m.text, m.url])),
  }
  mentionPatterns.set(links, made)
  return made
}

function withMentions(text: string, links?: MessageLinks): string {
  if (!links?.mentions.length) return text

  const { pattern, urls } = mentionPattern(links)
  return text
    .split(CODE_SPANS)
    .map((part, i) =>
      i % 2 ? part : part.replace(pattern, (m: string) => `[${m}](${urls.get(m)})`),
    )
    .join('')
}

export const Markdown = memo(function Markdown({
  text,
  className,
  links,
}: {
  text: string
  className?: string
  links?: MessageLinks
}) {
  const components = useMemo<Components>(() => {
    const flagged = new Set(links?.unverified ?? [])
    if (!flagged.size) return MARKDOWN_COMPONENTS

    return {
      a: ({ node: _node, ...p }) =>
        p.href && flagged.has(p.href) ? (
          <a
            {...p}
            target="_blank"
            rel="noreferrer"
            title={UNVERIFIED_TITLE}
            className="decoration-warn underline decoration-dotted underline-offset-2"
          >
            {p.children}
            <ExclamationTriangleIcon className="text-warn ml-0.5 inline size-3 align-[-1px]" />
          </a>
        ) : (
          <a {...p} target="_blank" rel="noreferrer" />
        ),
    }
  }, [links])

  return (
    <div className={cn('md', className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
        {withMentions(text, links)}
      </ReactMarkdown>
    </div>
  )
})

export function Label({ children }: { children: ReactNode }) {
  return (
    <div className="mb-1 flex items-baseline justify-between gap-3">
      <span className="text-text text-[12px] font-medium">{children}</span>
    </div>
  )
}

export function GithubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden className={cn('size-4', className)}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

export const SWITCH_TRACK = 'relative h-4 w-7 shrink-0 rounded-full transition-colors'

export function SwitchKnob({ on }: { on: boolean }) {
  return (
    <span
      className={cn(
        'absolute top-0.5 size-3 rounded-full bg-white shadow transition-all',
        on ? 'left-3.5' : 'left-0.5',
      )}
    />
  )
}

export function GithubBadge() {
  return (
    <IconBadge tone="neutral">
      <GithubMark className="size-5" />
    </IconBadge>
  )
}

export function Page({
  title,
  subtitle,
  actions,
  children,
  footer,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="flex h-full min-w-0 flex-col bg-white">
      {title || actions ? (
        <header className="border-line flex min-h-16 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b px-6 py-2.5">
          <div className="min-w-[min(100%,260px)] flex-1">
            {title ? (
              <div className="text-fg truncate text-[15px] leading-6 font-semibold">{title}</div>
            ) : null}
            {subtitle ? (
              <div className="text-muted flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px]">
                {subtitle}
              </div>
            ) : null}
          </div>
          {actions ? (
            <div className="flex max-w-full min-w-0 flex-wrap items-center gap-1">{actions}</div>
          ) : null}
        </header>
      ) : null}
      <div className="@container min-h-0 flex-1 scrollbar-thin overflow-y-auto">{children}</div>
      {footer}
    </div>
  )
}

export function Dot() {
  return <span className="bg-line-strong size-1 shrink-0 rounded-full" />
}

export type BadgeTone = 'brand' | 'ok' | 'warn' | 'danger' | 'neutral'

const BADGE_TONES: Record<BadgeTone, string> = {
  brand: 'bg-brand-soft text-brand-strong',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  danger: 'bg-danger-soft text-danger',
  neutral: 'bg-raised text-fg',
}

const BADGE_SIZES = {
  sm: ['size-8', 'size-4'],
  md: ['size-10', 'size-5'],
  lg: ['size-12', 'size-6'],
} as const

export function IconBadge({
  icon: Glyph,
  tone = 'brand',
  size = 'md',
  color,
  className,
  children,
}: {
  icon?: Icon
  tone?: BadgeTone
  size?: keyof typeof BADGE_SIZES
  color?: string
  className?: string
  children?: ReactNode
}) {
  const [box, glyph] = BADGE_SIZES[size]

  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full',
        box,
        !color && BADGE_TONES[tone],
        className,
      )}
      style={color ? { background: `${color}14`, color } : undefined}
    >
      {children ?? (Glyph ? <Glyph className={glyph} /> : null)}
    </span>
  )
}

export function EmptyState({
  icon,
  badge,
  title,
  children,
  error,
  action,
}: {
  icon?: Icon
  badge?: ReactNode
  title: ReactNode
  children?: ReactNode
  error?: ReactNode
  action?: ReactNode
}) {
  return (
    <Card className="w-full max-w-[480px] p-6 text-center">
      <div className="flex justify-center">{badge ?? <IconBadge icon={icon} size="lg" />}</div>
      <div className="text-fg mt-4 text-[15px] font-semibold">{title}</div>
      {children ? (
        <div className="text-muted mt-1 text-[13px] leading-relaxed">{children}</div>
      ) : null}
      {error ? <div className="text-danger mt-3 text-[12.5px]">{error}</div> : null}
      {action ? <div className="mt-5 flex justify-center gap-2">{action}</div> : null}
    </Card>
  )
}
