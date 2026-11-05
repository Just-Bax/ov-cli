import { createContext, useContext } from 'react'
import type { MessageFile, RunEvent, RunState } from '@shared/types.ts'

const IMAGE_TYPE = 'image/'
const TEXT_TYPE = 'text/'
const PDF_TYPE = 'application/pdf'
const EMAIL_NAME = /\.(eml|msg)$/i

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

export function fileOf(file: File): MessageFile {
  if (EMAIL_NAME.test(file.name)) return { name: file.name, kind: 'email' }
  if (file.type.startsWith(IMAGE_TYPE))
    return { name: file.name, kind: 'image', localUrl: URL.createObjectURL(file) }
  if (file.type === PDF_TYPE) return { name: file.name, kind: 'pdf' }
  if (file.type.startsWith(TEXT_TYPE)) return { name: file.name, kind: 'text' }
  return { name: file.name, kind: 'other' }
}

export function stopEvents(state: RunState): RunEvent[] {
  const now = Date.now()
  const stopped: RunEvent[] = state.tools
    .filter((t) => t.status === 'running' && t.stoppedAt === undefined)
    .map((t) => ({ type: 'tool', tool: { id: t.id, stoppedAt: now } }))
  return [{ type: 'status', status: 'cancelled' }, ...stopped]
}
