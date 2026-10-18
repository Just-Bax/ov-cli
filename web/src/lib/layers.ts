import { useEffect, useRef } from 'react'

type Layer = { close: () => void }

const stack: Layer[] = []

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing) return
  const top = stack.at(-1)
  if (!top) return
  e.preventDefault()
  e.stopPropagation()
  top.close()
})

export function layerOpen(): boolean {
  return stack.length > 0
}

export function useLayer(onClose: () => void, open = true): void {
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    if (!open) return

    const layer: Layer = { close: () => close.current() }
    const returnTo = document.activeElement as HTMLElement | null
    stack.push(layer)

    return () => {
      stack.splice(stack.indexOf(layer), 1)
      if (returnTo?.isConnected) returnTo.focus({ preventScroll: true })
    }
  }, [open])
}
