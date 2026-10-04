import { useEffect, useState } from 'react'

export type Route =
  { page: 'home' } | { page: 'settings' } | { page: 'map' } | { page: 'run'; id: string }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/')
  if (parts[0] === 'run' && parts[1]) return { page: 'run', id: parts[1] }
  if (parts[0] === 'settings') return { page: 'settings' }
  if (parts[0] === 'map') return { page: 'map' }
  return { page: 'home' }
}

export function href(route: Route): string {
  return route.page === 'run'
    ? `#/run/${route.id}`
    : route.page === 'home'
      ? '#/'
      : `#/${route.page}`
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
