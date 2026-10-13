import { useEffect, useState } from 'react'

const SIMPLE_PAGES = ['settings', 'map', 'explorer', 'health'] as const

type SimplePage = (typeof SIMPLE_PAGES)[number]

export type Route = { page: 'home' } | { page: SimplePage } | { page: 'thread'; id: string }

function parse(hash: string): Route {
  const [page, id] = hash.replace(/^#\/?/, '').split('/')
  if (page === 'thread' && id) return { page: 'thread', id }
  const simple = SIMPLE_PAGES.find((p) => p === page)
  return simple ? { page: simple } : { page: 'home' }
}

export function href(route: Route): string {
  if (route.page === 'thread') return `#/thread/${route.id}`
  return route.page === 'home' ? '#/' : `#/${route.page}`
}

export function go(route: Route): void {
  window.location.hash = href(route)
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return route
}
