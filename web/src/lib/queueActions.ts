import type { ChatMessage } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { api } from '@/lib/api'
import { useApply } from '@/lib/optimistic'

export function useQueueActions(runId: string, queued: ChatMessage[], held: boolean) {
  const apply = useApply()
  const order = queued.map((m) => m.id)
  const steering = (also?: string) =>
    queued.filter((m) => m.steer || m.id === also).map((m) => m.id)

  return {
    remove: (id: string) => {
      apply({ type: 'unqueue', id })
      void api.removeQueued(runId, id).catch(reportError)
    },
    steer: (id: string) => {
      apply({ type: 'queue', order, steering: steering(id), held })
      void api.steerQueued(runId, id).catch(reportError)
    },
    resume: () => {
      apply({ type: 'queue', order, steering: steering(), held: false })
      void api.resumeQueue(runId).catch(reportError)
    },
  }
}
