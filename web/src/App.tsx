import { useCallback, useEffect, useState } from 'react'
import type { Settings, Status } from '@shared/types.ts'
import { DialogHost, dialog } from '@/components/Dialog'
import { Home } from '@/components/Home'
import { MapPage } from '@/components/map/MapPage'
import { RunView } from '@/components/run/RunView'
import { SettingsPage } from '@/components/Settings'
import wordmark from '@/assets/ov-agent-wordmark.svg'
import { Setup } from '@/components/Setup'
import { Sidebar } from '@/components/Sidebar'
import { Skeleton } from '@/components/ui'
import { api } from '@/lib/api'
import { useRoute } from '@/lib/route'
import { SettingsContext } from '@/lib/settings'

export function App() {
  const route = useRoute()
  const [status, setStatus] = useState<Status>()
  const [error, setError] = useState<string>()

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

  const update = useCallback(async (patch: Partial<Settings>) => {
    const settings = await api.saveSettings(patch)
    setStatus((s) => (s ? { ...s, settings } : s))
    // An ov agent started before an upgrade serves the new page but drops settings it does not know.
    if (Object.keys(patch).some((key) => !(key in settings)))
      await dialog.alert(
        'Restart ov agent',
        'The running server is older than this page and could not save that setting. Stop it with Ctrl+C, start ov agent again, then reload this tab.',
        'warn',
      )
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
  if (!status) {
    return (
      <div className="flex h-full">
        <aside className="border-line-strong/60 flex w-[272px] shrink-0 flex-col border-r bg-white">
          <div className="flex h-16 items-center px-5">
            <img src={wordmark} alt="OV Agent" className="h-[26px] w-auto" />
          </div>
          <div className="px-3">
            <Skeleton className="h-10 w-full rounded-full" />
          </div>
          <div className="mt-6 space-y-4 px-5">
            {['w-4/5', 'w-3/5', 'w-11/12', 'w-2/3'].map((w) => (
              <Skeleton key={w} className={`h-3 ${w}`} />
            ))}
          </div>
        </aside>
        <main className="flex flex-1 items-center justify-center bg-white">
          <div className="w-full max-w-[720px] px-6">
            <Skeleton className="mx-auto h-7 w-[420px] max-w-full rounded-full" />
            <div className="border-line mt-6 rounded-[26px] border p-4 shadow-[0_2px_12px_rgba(38,50,56,0.04)]">
              <Skeleton className="h-3.5 w-2/3" />
              <div className="mt-8 flex items-center gap-2">
                <Skeleton className="size-7 rounded-full" />
                <Skeleton className="h-3 w-32" />
                <div className="flex-1" />
                <Skeleton className="size-8 rounded-full" />
              </div>
            </div>
            <div className="mt-8 grid grid-cols-2 gap-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="border-line space-y-2 rounded-2xl border p-3">
                  <Skeleton className="h-2.5 w-24" />
                  <Skeleton className="h-3 w-11/12" />
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    )
  }

  const needsSetup = !status.ready
  if (needsSetup && route.page !== 'settings')
    return (
      <>
        <Setup status={status} onDone={refresh} />
        <DialogHost />
      </>
    )

  return (
    <SettingsContext.Provider value={{ settings: status.settings, update }}>
      <div className="flex h-full">
        <Sidebar route={route} user={status.copilot.user} />
        <main className="min-w-0 flex-1">
          {route.page === 'home' && <Home settings={status.settings} />}
          {route.page === 'settings' && <SettingsPage onChange={refresh} />}
          {route.page === 'map' && <MapPage />}
          {route.page === 'run' && <RunView key={route.id} id={route.id} />}
        </main>
        <DialogHost />
      </div>
    </SettingsContext.Provider>
  )
}
