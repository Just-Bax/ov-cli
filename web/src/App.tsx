import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import type { Settings, Status } from '@shared/types.ts'
import { CommandPalette } from '@/components/layout/CommandPalette'
import { DialogHost } from '@/components/common/Dialog'
import { Home } from '@/components/home/Home'
import { RunView } from '@/components/run/RunView'
import { Setup } from '@/components/settings/Setup'
import { Sidebar } from '@/components/layout/Sidebar'
import { Toasts } from '@/components/common/Toasts'
import { HomeSkeleton } from '@/components/common/skeletons'
import { api } from '@/lib/api'
import { useRoute } from '@/lib/route'
import { SettingsContext } from '@/lib/settings'

const ExplorerPage = lazy(() =>
  import('@/components/explorer/ExplorerPage').then((m) => ({ default: m.ExplorerPage })),
)
const MapPage = lazy(() => import('@/components/map/MapPage').then((m) => ({ default: m.MapPage })))
const HealthPage = lazy(() =>
  import('@/components/health/HealthPage').then((m) => ({ default: m.HealthPage })),
)
const WalkthroughsPage = lazy(() =>
  import('@/components/walkthroughs/WalkthroughsPage').then((m) => ({
    default: m.WalkthroughsPage,
  })),
)
const SettingsPage = lazy(() =>
  import('@/components/settings/Settings').then((m) => ({ default: m.SettingsPage })),
)

export function App() {
  const route = useRoute()
  const [status, setStatus] = useState<Status>()
  const [error, setError] = useState<string>()
  const [inSetup, setInSetup] = useState(false)

  const refresh = useCallback(() => {
    api
      .status()
      .then((s) => {
        setStatus(s)
        setError(undefined)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(refresh, [refresh])
  useEffect(() => {
    if (status && !status.ready) setInSetup(true)
  }, [status?.ready])

  const update = useCallback(async (patch: Partial<Settings>) => {
    const settings = await api.saveSettings(patch)
    setStatus((s) => (s ? { ...s, settings } : s))
  }, [])

  if (error && !status) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <div>
          <div className="text-[14px] font-medium">Cannot reach the OV Agent server</div>
          <div className="text-muted mt-1">{error}. Is `ov agent` still running?</div>
        </div>
      </div>
    )
  }

  if (!status)
    return (
      <div className="flex h-full">
        <Sidebar route={route} loading />
        <main className="min-w-0 flex-1 bg-white">
          {route.page === 'home' ? <HomeSkeleton /> : null}
        </main>
      </div>
    )

  if (!status.ready || inSetup)
    return (
      <>
        <Setup status={status} onDone={refresh} onFinish={() => setInSetup(false)} />
        <DialogHost />
        <Toasts />
      </>
    )

  return (
    <SettingsContext.Provider value={{ settings: status.settings, update }}>
      <div className="flex h-full">
        <Sidebar route={route} user={status.copilot.user} />
        <main
          key={route.page === 'thread' ? `run-${route.id}` : route.page}
          className="animate-fade-in min-w-0 flex-1 bg-white"
        >
          <Suspense fallback={null}>
            {route.page === 'home' && <Home />}
            {route.page === 'settings' && <SettingsPage onChange={refresh} />}
            {route.page === 'map' && <MapPage />}
            {route.page === 'health' && <HealthPage />}
            {route.page === 'walkthroughs' && <WalkthroughsPage />}
            {route.page === 'explorer' && <ExplorerPage />}
            {route.page === 'thread' && <RunView key={route.id} id={route.id} />}
          </Suspense>
        </main>
        <DialogHost />
        <Toasts />
        <CommandPalette route={route} />
      </div>
    </SettingsContext.Provider>
  )
}
