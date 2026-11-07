import { createContext, useContext } from 'react'
import type { MessageFile, RunEvent, RunState } from '@shared/types.ts'

const IMAGE_TYPE = 'image/'
const TEXT_TYPE = 'text/'
const PDF_TYPE = 'application/pdf'
const EMAIL_NAME = /\.(eml|msg)$/i
const TEXT_NAME = /\.(txt|log|csv|json|xml|sql|py|js|ts|html|md|yaml|yml)$/i

export type Apply = (event: RunEvent) => void

export const ApplyContext = createContext<Apply | undefined>(undefined)

export function useApply(): Apply {
  const apply = useContext(ApplyContext)
  if (!apply) throw new Error('useApply must be used inside a thread view')
  return apply
}

export function newMessageId(): string {
  return `u_${crypto.randomUUID().replace(/-/g, '')}`
}

export function kindOf(file: File): MessageFile['kind'] {
  if (EMAIL_NAME.test(file.name)) return 'email'
  if (file.type.startsWith(IMAGE_TYPE)) return 'image'
  if (file.type === PDF_TYPE) return 'pdf'
  if (file.type.startsWith(TEXT_TYPE) || TEXT_NAME.test(file.name)) return 'text'
  return 'other'
}

export function fileOf(file: File): MessageFile {
  const kind = kindOf(file)
  const localUrl = kind === 'image' ? URL.createObjectURL(file) : undefined
  return { name: file.name, kind, size: file.size, localUrl }
}

export function stopEvents(state: RunState): RunEvent[] {
  const now = Date.now()
  const stopped: RunEvent[] = state.tools
    .filter((t) => t.status === 'running' && t.stoppedAt === undefined)
    .map((t) => ({ type: 'tool', tool: { id: t.id, stoppedAt: now } }))
  return [{ type: 'status', status: 'cancelled' }, ...stopped]
}
