import {
  ChatsCircle as ThreadIcon,
  File as FileIcon,
  FileText as FileTextIcon,
  Folder as FolderIcon,
  Image as ImageIcon,
  Sparkle as SkillIcon,
} from '@phosphor-icons/react'
import { createContext, useContext } from 'react'
import type { GraphNodeType } from '@shared/types.ts'
import type { Icon } from '@/components/common/ui'
import { TYPES } from '@/components/map/meta'
import { cn } from '@/lib/cn'
import { type Mention, splitMentions } from '@/lib/mentions'
import { fileSize } from '@/lib/text'

const IMAGE_NAME = /\.(png|jpe?g|gif|webp|bmp)$/i
const TEXT_NAME = /\.(txt|log|csv|json|xml|sql|py|js|ts|tsx|html|md|ya?ml|eml|msg)$/i

export interface ChipFile {
  size?: number
  url?: string
}

export const MentionFiles = createContext<(name: string) => ChipFile | undefined>(() => undefined)

function attachmentIcon(name: string): Icon {
  if (IMAGE_NAME.test(name)) return ImageIcon
  return TEXT_NAME.test(name) ? FileTextIcon : FileIcon
}

function objectType(target: string): GraphNodeType | undefined {
  const type = target.split('/')[0]
  return type in TYPES ? (type as GraphNodeType) : undefined
}

function look(mention: Mention): { icon: Icon; color?: string; title: string } {
  switch (mention.kind) {
    case 'attachment':
      return { icon: attachmentIcon(mention.target), title: `Attached file ${mention.target}` }
    case 'workspace':
      return mention.target.endsWith('/')
        ? { icon: FolderIcon, title: `Workspace folder ${mention.target}` }
        : { icon: attachmentIcon(mention.target), title: `Workspace file ${mention.target}` }
    case 'thread':
      return { icon: ThreadIcon, title: `Thread ${mention.label}` }
    case 'skill':
      return { icon: SkillIcon, title: `Skill ${mention.label}` }
    case 'ov': {
      const type = objectType(mention.target)
      if (!type) return { icon: FileIcon, title: mention.target }

      const meta = TYPES[type]
      const id = mention.target.split('/')[1]
      return { icon: meta.icon, color: meta.color, title: `${meta.label} ${mention.label} (${id})` }
    }
  }
}

export function MentionChip({ mention, selected }: { mention: Mention; selected?: boolean }) {
  const files = useContext(MentionFiles)
  const file = mention.kind === 'attachment' ? files(mention.target) : undefined
  const { icon: KindIcon, color, title } = look(mention)

  return (
    <span
      title={title}
      className={cn(
        'border-line-strong/70 bg-raised mx-px inline-flex max-w-[320px] items-center gap-1 rounded-md border px-1.5 align-[-4px] text-[12.5px] leading-[20px] whitespace-nowrap',
        selected && 'border-brand',
      )}
    >
      {file?.url && IMAGE_NAME.test(mention.target) ? (
        <img src={file.url} alt="" className="size-3.5 shrink-0 rounded-[3px] object-cover" />
      ) : (
        <KindIcon
          weight="bold"
          className={cn('size-3.5 shrink-0', !color && 'text-muted')}
          style={color ? { color } : undefined}
        />
      )}
      <span className="text-brand-strong truncate">{mention.label}</span>
      {file?.size !== undefined ? (
        <span className="text-faint shrink-0 text-[11px]">{fileSize(file.size)}</span>
      ) : null}
    </span>
  )
}

export function MentionText({ text }: { text: string }) {
  return splitMentions(text).map((part, i) =>
    typeof part === 'string' ? part : <MentionChip key={i} mention={part} />,
  )
}
