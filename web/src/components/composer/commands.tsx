import {
  ArrowsInLineVertical as CompactIcon,
  Checks as SettleIcon,
  ArrowCounterClockwise as ActiveIcon,
  DownloadSimple as ExportIcon,
  Globe as InstanceIcon,
  MagnifyingGlass as FindIcon,
  Plus as NewIcon,
  ShieldCheck as AccessIcon,
  Stop as StopIcon,
} from '@phosphor-icons/react'
import type { Access, Instance, RunSummary } from '@shared/types.ts'
import { OPEN_FIND } from '@/components/layout/CommandPalette'
import { BranchIcon, openThread } from '@/components/run/Branches'
import { api } from '@/lib/api'
import { useLoad } from '@/lib/hooks'
import { instanceLabel } from '@/lib/instances'
import { go } from '@/lib/route'
import { setSettled } from '@/lib/runs'
import { ACCESS_MODES, confirmAccess } from './AccessPicker'
import type { ComposerCommand } from './menu'

const ICON = 'text-muted size-4'

export function useAccessCommand(onChange: (next: Access) => void | Promise<unknown>) {
  const { value: status } = useLoad(api.status, [])

  return {
    name: 'access',
    description: 'Change what the agent may do',
    icon: <AccessIcon weight="bold" className={ICON} />,
    options: ACCESS_MODES.filter((m) => m.value !== 'full' || status?.fullAccess).map((m) => ({
      value: m.value,
      label: m.label,
      detail: m.about,
    })),
    run: async (value) => {
      const next = value as Access
      if (await confirmAccess(next)) await onChange(next)
    },
  } satisfies ComposerCommand
}

export function instanceCommand(
  instances: Instance[],
  onChange: (alias: string) => void,
): ComposerCommand {
  return {
    name: 'instance',
    description: 'Pick the instance for this thread',
    icon: <InstanceIcon weight="bold" className={ICON} />,
    options: [
      { value: '', label: 'Auto', detail: 'from context' },
      ...instances
        .filter((i) => i.valid)
        .map((i) => ({ value: i.alias, label: instanceLabel(i), detail: i.alias })),
    ],
    run: (value) => onChange(value ?? ''),
  }
}

export function threadCommands(
  run: RunSummary,
  settled: boolean,
  busy: boolean,
  onStop: () => void,
): ComposerCommand[] {
  const commands: ComposerCommand[] = [
    {
      name: 'new',
      description: 'Start a new thread',
      icon: <NewIcon weight="bold" className={ICON} />,
      run: () => go({ page: 'home' }),
    },
    {
      name: 'branch',
      description: 'Branch this thread from the latest answer',
      icon: <BranchIcon className={ICON} />,
      run: () => openThread(api.branch(run.id)),
    },
    {
      name: 'find',
      description: 'Find text in this thread',
      icon: <FindIcon weight="bold" className={ICON} />,
      run: () => window.dispatchEvent(new Event(OPEN_FIND)),
    },
    {
      name: 'export',
      description: 'Download this thread as Markdown',
      icon: <ExportIcon weight="bold" className={ICON} />,
      run: () => window.location.assign(api.exportUrl(run.id)),
    },
  ]

  if (settled || run.status !== 'waiting')
    commands.push({
      name: settled ? 'active' : 'settle',
      description: settled ? 'Move this thread back to active' : 'Settle this thread',
      icon: settled ? (
        <ActiveIcon weight="bold" className={ICON} />
      ) : (
        <SettleIcon weight="bold" className={ICON} />
      ),
      run: () => setSettled(run.id, !settled),
    })

  if (busy)
    return [
      {
        name: 'stop',
        description: 'Stop the agent',
        icon: <StopIcon weight="bold" className={ICON} />,
        run: onStop,
      },
      ...commands,
    ]

  return [
    {
      name: 'compact',
      description: 'Compact the context into a summary',
      icon: <CompactIcon weight="bold" className={ICON} />,
      run: async () => {
        await api.compactRun(run.id)
      },
    },
    ...commands,
  ]
}
