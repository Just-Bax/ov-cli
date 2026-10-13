import { dismissToast, notifyAction, reportError } from '@/components/Toasts'

const UNDO_MS = 5000

let last: { undo: () => Promise<void>; toast: number; at: number } | undefined

function editable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return Boolean(
    el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable),
  )
}

function runUndo() {
  const action = last
  last = undefined
  if (!action || Date.now() - action.at > UNDO_MS) return
  dismissToast(action.toast)
  void action.undo().catch(reportError)
}

window.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.key.toLowerCase() !== 'z') return
  if (editable(e.target) || !last) return
  e.preventDefault()
  runUndo()
})

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
