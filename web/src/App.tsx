import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import type { Settings, Status } from '@shared/types.ts'
import { CommandPalette } from '@/components/layout/CommandPalette'
import { DialogHost } from '@/components/common/Dialog'
import { Home } from '@/components/home/Home'
import { RunView } from '@/components/run/RunView'
import { Setup } from '@/components/settings/Setup'
import { Sidebar } from '@/components/layout/Sidebar'
import { sidebarAccount } from '@/components/providers'
import { Toasts } from '@/components/common/Toasts'
import { HomeSkeleton } from '@/components/common/skeletons'
import { api } from '@/lib/api'
import { configureAttention } from '@/lib/attention'
import { useRoute } from '@/lib/route'
import { SettingsContext } from '@/lib/settings'

const ExplorerPage = lazy(() =>
  import('@/components/explorer/ExplorerPage').then((m) => ({ default: m.ExplorerPage })),
)
const MapPage = lazy(() => import('@/components/map/MapPage').then((m) => ({ default: m.MapPage })))
const HealthPage = lazy(() =>
  import('@/components/health/HealthPage').then((m) => ({ default: m.HealthPage })),
)
const SettingsPage = lazy(() =>
  import('@/components/settings/Settings').then((m) => ({ default: m.SettingsPage })),
)

function needsOnboarding(status: Status): boolean {
  return status.instances.total === 0 || !status.providers.some((p) => p.account.signedIn)
}

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
    if (status) configureAttention(status.settings)
  }, [status?.settings.notify, status?.settings.tabBadge])

  const onboarding = status ? needsOnboarding(status) : false

  useEffect(() => {
    if (onboarding) setInSetup(true)
  }, [onboarding])

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

  if (onboarding || inSetup)
    return (
      <>
        <Setup status={status} onDone={refresh} onFinish={() => setInSetup(false)} />
        <DialogHost />
        <Toasts />
      </>
    )

  return (
    <SettingsContext.Provider
      value={{ settings: status.settings, providers: status.providers, update }}
    >
      <div className="flex h-full">
        <Sidebar route={route} account={sidebarAccount(status)} />
        <main
          key={route.page === 'thread' ? `run-${route.id}` : route.page}
          className="min-w-0 flex-1 bg-white"
        >
          <Suspense fallback={null}>
            {route.page === 'home' && <Home />}
            {route.page === 'settings' && <SettingsPage onChange={refresh} />}
            {route.page === 'map' && <MapPage />}
            {route.page === 'health' && <HealthPage />}
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
