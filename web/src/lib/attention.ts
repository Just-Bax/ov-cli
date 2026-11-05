import type { RunList, RunStatus } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { go } from '@/lib/route'

export interface StatusChange {
  kind: 'status'
  id: string
  status: RunStatus
  title: string
}

const BADGE_SIZE = 64
const DOT_RADIUS = 15
const DOT_RING = 5
const DOT_COLOR = '#f5b400'
const RING_COLOR = '#ffffff'
const ICON_URL = '/favicon.svg'
const NOTIFICATION_ICON = '/icon-192.png'
const APP_TITLE = 'OV Agent'
const THREAD_HASH = /^#\/thread\/([a-z0-9]+)/

const MESSAGES: Partial<Record<RunStatus, string>> = {
  waiting: 'Needs your answer',
  done: 'Finished',
  error: 'Stopped with an error',
}

let notify = false
let badge = true
let waiting = new Set<string>()
const unseen = new Set<string>()
let icons: { link: HTMLLinkElement; href: string }[] | undefined
let badged: Promise<string> | undefined
let shown = false

export function notificationsSupported(): boolean {
  return 'Notification' in window
}

export function notificationsBlocked(): boolean {
  return notificationsSupported() && Notification.permission === 'denied'
}

export async function allowNotifications(): Promise<boolean> {
  if (!notificationsSupported()) return false
  if (Notification.permission === 'granted') return true
  return (await Notification.requestPermission()) === 'granted'
}

export function configureAttention(options: { notify: boolean; tabBadge: boolean }): void {
  notify = options.notify
  badge = options.tabBadge
  refresh()
}

export function noteRuns(list: RunList): void {
  waiting = new Set(list.active.filter((r) => r.status === 'waiting').map((r) => r.id))
  refresh()
}

export function noteStatus(change: StatusChange): void {
  const message = MESSAGES[change.status]
  if (!message || viewing(change.id)) return
  if (change.status !== 'waiting') unseen.add(change.id)
  refresh()
  if (notify && notificationsSupported() && Notification.permission === 'granted')
    announce(change, message)
}

function announce(change: StatusChange, message: string) {
  const note = new Notification(change.title || APP_TITLE, {
    body: message,
    icon: NOTIFICATION_ICON,
    tag: `ov-${change.id}`,
  })

  note.onclick = () => {
    window.focus()
    go({ page: 'thread', id: change.id })
    note.close()
  }
}

function openThread(): string | undefined {
  return THREAD_HASH.exec(window.location.hash)?.[1]
}

function viewing(id: string): boolean {
  return document.visibilityState === 'visible' && document.hasFocus() && openThread() === id
}

function markSeen() {
  const id = openThread()
  if (!id || document.visibilityState !== 'visible') return
  unseen.delete(id)
  refresh()
}

function refresh() {
  const count = new Set([...waiting, ...unseen]).size
  const show = badge && count > 0
  document.title = show ? `(${count}) ${APP_TITLE}` : APP_TITLE
  if (show !== shown) paint(show).catch(reportError)
  shown = show
}

async function paint(show: boolean) {
  icons ??= [...document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')].map((link) => ({
    link,
    href: link.href,
  }))

  const href = show ? await badgeIcon() : undefined
  if (show !== shown) return

  for (const icon of icons) icon.link.href = href ?? icon.href
}

function badgeIcon(): Promise<string> {
  badged ??= new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(drawBadge(image))
    image.onerror = () => reject(new Error(`Could not load ${ICON_URL} for the tab badge.`))
    image.src = ICON_URL
  })

  return badged
}

function drawBadge(image: HTMLImageElement): string {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = BADGE_SIZE
  const context = canvas.getContext('2d')
  if (!context) throw new Error('This browser cannot draw the tab badge.')

  context.drawImage(image, 0, 0, BADGE_SIZE, BADGE_SIZE)
  const center = BADGE_SIZE - DOT_RADIUS

  context.beginPath()
  context.arc(center, center, DOT_RADIUS, 0, 2 * Math.PI)
  context.fillStyle = RING_COLOR
  context.fill()
  context.beginPath()
  context.arc(center, center, DOT_RADIUS - DOT_RING, 0, 2 * Math.PI)
  context.fillStyle = DOT_COLOR
  context.fill()

  return canvas.toDataURL()
}

window.addEventListener('hashchange', markSeen)
window.addEventListener('focus', markSeen)
document.addEventListener('visibilitychange', markSeen)
