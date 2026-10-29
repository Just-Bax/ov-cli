import type { ChatMessage, RunStatus } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'
import { useApply } from '@/lib/optimistic'
import { patchLocally, WORKING } from '@/lib/runs'

export function useQueueActions(runId: string, queued: ChatMessage[], status: RunStatus) {
  const apply = useApply()
  const busy = WORKING.has(status)

  return {
    remove: (id: string) => {
      apply({ type: 'unqueue', id })
      void api.removeQueued(runId, id).catch(reportError)
    },
    send: (id: string) => {
      const message = queued.find((m) => m.id === id)
      if (!message) return

      apply({ type: 'user', message: { ...message, ts: Date.now(), steer: busy || undefined } })
      if (!busy) {
        apply({ type: 'status', status: 'running' })
        patchLocally(runId, { status: 'running' })
      }

      void api.sendQueued(runId, id).catch((e: unknown) => {
        apply({ type: 'rewind', itemId: id })
        apply({ type: 'queued', message })
        if (!busy) apply({ type: 'status', status })
        reportError(e)
      })
    },
    resume: () => {
      apply({ type: 'queue', order: queued.map((m) => m.id), steering: [], held: false })
      void api.resumeQueue(runId).catch(reportError)
    },
  }
}
