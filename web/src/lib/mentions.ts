export const MENTION_KINDS = ['attachment', 'workspace', 'ov', 'thread', 'skill'] as const
export type MentionKind = (typeof MENTION_KINDS)[number]
export interface Mention {
  kind: MentionKind
  target: string
  label: string
}

const MENTION = new RegExp(`\\[([^[\\]\\n]+)\\]\\((${MENTION_KINDS.join('|')}):([^()\\s]+)\\)`, 'g')
const HREF = new RegExp(`^(${MENTION_KINDS.join('|')}):(.+)$`)
const LABEL_BREAKS = /[[\]\n]+/g
const PARENS = /[()]/g

function encodeTarget(target: string): string {
  return target
    .split('/')
    .map((part) =>
      encodeURIComponent(part).replace(
        PARENS,
        (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
      ),
    )
    .join('/')
}

function decodeTarget(target: string): string {
  return decodeURIComponent(target)
}

export function mentionText({ kind, target, label }: Mention): string {
  const clean = label.replace(LABEL_BREAKS, ' ').trim()
  if (!clean) throw new Error(`A ${kind} mention needs a label.`)
  return `[${clean}](${kind}:${encodeTarget(target)})`
}

export function splitMentions(text: string): (string | Mention)[] {
  const parts: (string | Mention)[] = []
  let last = 0
  for (const m of text.matchAll(MENTION)) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    parts.push({ label: m[1], kind: m[2] as MentionKind, target: decodeTarget(m[3]) })
    last = m.index + m[0].length
  }

  if (last < text.length) parts.push(text.slice(last))

  return parts
}

export function mentionOfHref(href: string, label: string): Mention | undefined {
  const m = HREF.exec(href)
  return m ? { kind: m[1] as MentionKind, target: decodeTarget(m[2]), label } : undefined
}

export function mentionHrefAllowed(href: string): boolean {
  return HREF.test(href)
}

export function withoutAttachments(text: string): string {
  return splitMentions(text)
    .map((part) =>
      typeof part === 'string' ? part : part.kind === 'attachment' ? part.label : mentionText(part),
    )
    .join('')
}
