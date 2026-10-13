import { dismissToast, notifyAction, reportError } from '@/components/Toasts'

const UNDO_MS = 5000

let last: { undo: () => Promise<void>; toast: number; at: number } | undefined

export function canUndo(): boolean {
  return Boolean(last && Date.now() - last.at <= UNDO_MS)
}

export function runUndo(): void {
  const action = last
  last = undefined
  if (!action || Date.now() - action.at > UNDO_MS) return
  dismissToast(action.toast)
  void action.undo().catch(reportError)
}

export function remember(message: string, undo: () => Promise<void>): void {
  if (last) dismissToast(last.toast)
  const entry = { undo, at: Date.now(), toast: 0 }
  last = entry
  entry.toast = notifyAction(
    message,
    'Undo',
    () => {
      if (last === entry) runUndo()
    },
    UNDO_MS,
  )
}
