export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return Boolean(
    el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable),
  )
}

export function inCodeEditor(target: EventTarget | null): boolean {
  return Boolean((target as HTMLElement | null)?.closest?.('.monaco-editor'))
}
