import {
  ChatsCircle as ThreadIcon,
  File as FileIcon,
  Folder as FolderIcon,
  Paperclip as AttachedIcon,
  Sparkle as SkillIcon,
} from '@phosphor-icons/react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import type { GraphNode, InstanceGraph, SkillInfo, WorkspacePath } from '@shared/types.ts'
import { reportError } from '@/components/common/Toasts'
import { index as graphIndex, type Index, TypeDot, TYPES } from '@/components/map/meta'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { rank } from '@/lib/fuzzy'
import { useActiveIntoView } from '@/lib/hooks'
import type { Mention } from '@/lib/mentions'
import { refIndex } from '@/lib/references'
import { allRuns, useRuns } from '@/lib/runs'
import type { Trigger } from './editor'

const PATHS_DEBOUNCE_MS = 120
const COMMAND_LIMIT = 12
const SKILL_LIMIT = 8
const ATTACHED_LIMIT = 8
const OBJECT_LIMIT = 8
const THREAD_LIMIT = 5
const PATH_LIMIT = 8

export interface CommandOption {
  value: string
  label: string
  detail?: string
}

export interface ComposerCommand {
  name: string
  description: string
  icon: ReactNode
  options?: CommandOption[]
  run: (value?: string) => void | Promise<void>
}

export type MenuAction =
  | { type: 'mention'; mention: Mention }
  | { type: 'command'; command: ComposerCommand }
  | { type: 'option'; command: ComposerCommand; value: string }

export interface MenuItem {
  key: string
  group: string
  label: string
  detail?: string
  icon: ReactNode
  action: MenuAction
}

const graphs = new Map<string, Promise<InstanceGraph>>()

function cachedGraph(alias: string, builtAt: number): Promise<InstanceGraph> {
  const key = `${alias}:${builtAt}`
  const found = graphs.get(key)
  if (found) return found

  const made = api.graph(alias)
  graphs.set(key, made)
  made.catch(() => graphs.delete(key))
  return made
}

export function useMentionGraph(alias: string | undefined) {
  const [graph, setGraph] = useState<InstanceGraph>()

  useEffect(() => {
    setGraph(undefined)
    if (!alias) return

    let alive = true
    api
      .graphStatus(alias)
      .then((status) => (status.builtAt ? cachedGraph(alias, status.builtAt) : undefined))
      .then((found) => alive && setGraph(found))
      .catch(reportError)

    return () => {
      alive = false
    }
  }, [alias])

  return useMemo(() => {
    if (!graph) return undefined

    const idx = graphIndex(graph)
    return { nodes: graph.nodes, idx, refs: refIndex(graph.nodes, idx) }
  }, [graph])
}

function useSkills(active: boolean): SkillInfo[] {
  const [skills, setSkills] = useState<SkillInfo[]>([])

  useEffect(() => {
    if (!active) return

    let alive = true
    api
      .skills()
      .then((found) => alive && setSkills(found.filter((s) => s.enabled)))
      .catch(reportError)

    return () => {
      alive = false
    }
  }, [active])

  return skills
}

function useWorkspacePaths(active: boolean, query: string): WorkspacePath[] {
  const [paths, setPaths] = useState<WorkspacePath[]>([])

  useEffect(() => {
    if (!active) return

    const abort = new AbortController()
    const timer = setTimeout(() => {
      api
        .workspacePaths(query, abort.signal)
        .then((found) => setPaths(found.paths))
        .catch((e: unknown) => {
          if (!abort.signal.aborted) reportError(e)
        })
    }, PATHS_DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      abort.abort()
    }
  }, [active, query])

  return paths
}

function objectDetail(node: GraphNode, idx: Index): string {
  const label = TYPES[node.type].label
  if (node.type !== 'field') return `${label} ${node.ref}`

  const owner = idx.links.get(node.id)?.find((l) => l.kind === 'field_of' && l.out)?.other
  return owner ? `Field of ${owner.name}` : `${label} ${node.ref}`
}

function objectItems(graph: { nodes: GraphNode[]; idx: Index }, query: string): MenuItem[] {
  const found = rank(
    graph.nodes,
    query,
    (n) => [n.name, `${TYPES[n.type].label} ${n.ref}`],
    OBJECT_LIMIT,
  )

  return found.map((node) => ({
    key: `ov:${node.id}`,
    group: 'Instance objects',
    label: node.name,
    detail: objectDetail(node, graph.idx),
    icon: <TypeDot type={node.type} />,
    action: {
      type: 'mention',
      mention: { kind: 'ov', target: `${node.type}/${node.ref}`, label: node.name },
    },
  }))
}

function skillItem(skill: SkillInfo): MenuItem {
  return {
    key: `skill:${skill.name}`,
    group: 'Skills',
    label: skill.title,
    detail: skill.description,
    icon: <SkillIcon weight="bold" className="text-muted size-4" />,
    action: { type: 'mention', mention: { kind: 'skill', target: skill.name, label: skill.title } },
  }
}

function slashItems(trigger: Trigger, commands: ComposerCommand[], skills: SkillInfo[]) {
  if (trigger.command !== undefined) {
    const command = commands.find((c) => c.name === trigger.command)
    if (!command?.options) return []

    return rank(command.options, trigger.query, (o) => [o.label, o.detail], COMMAND_LIMIT).map(
      (option): MenuItem => ({
        key: `option:${option.value}`,
        group: `/${command.name}`,
        label: option.label,
        detail: option.detail,
        icon: command.icon,
        action: { type: 'option', command, value: option.value },
      }),
    )
  }

  const found = rank(commands, trigger.query, (c) => [c.name, c.description], COMMAND_LIMIT).map(
    (command): MenuItem => ({
      key: `command:${command.name}`,
      group: 'Commands',
      label: `/${command.name}`,
      detail: command.description,
      icon: command.icon,
      action: { type: 'command', command },
    }),
  )

  const picked = rank(
    skills,
    trigger.query,
    (s) => [s.name, `${s.title} ${s.description}`],
    SKILL_LIMIT,
  )
  return [...found, ...picked.map(skillItem)]
}

export interface MentionSources {
  commands: ComposerCommand[]
  attachments: string[]
  graph?: { nodes: GraphNode[]; idx: Index }
  runId?: string
}

export function useMenuItems(trigger: Trigger | undefined, sources: MentionSources): MenuItem[] {
  const char = trigger?.char
  const query = trigger?.query ?? ''
  const skills = useSkills(char === '/' || char === '$')
  const paths = useWorkspacePaths(char === '@', query)
  const runs = useRuns()
  const { commands, attachments, graph, runId } = sources

  return useMemo(() => {
    if (!trigger) return []
    if (trigger.char === '/') return slashItems(trigger, commands, skills)
    if (trigger.char === '$')
      return rank(skills, query, (s) => [s.name, `${s.title} ${s.description}`], COMMAND_LIMIT).map(
        skillItem,
      )

    const attached = rank(attachments, query, (name) => [name], ATTACHED_LIMIT).map(
      (name): MenuItem => ({
        key: `attachment:${name}`,
        group: 'Attached',
        label: name,
        icon: <AttachedIcon weight="bold" className="text-muted size-4" />,
        action: { type: 'mention', mention: { kind: 'attachment', target: name, label: name } },
      }),
    )

    const objects = graph && query ? objectItems(graph, query) : []

    const threads = rank(
      allRuns(runs).filter((r) => r.id !== runId),
      query,
      (r) => [r.title, r.instance],
      THREAD_LIMIT,
    )

    return [
      ...attached,
      ...objects,
      ...threads.map((run): MenuItem => ({
        key: `thread:${run.id}`,
        group: 'Threads',
        label: run.title,
        detail: run.instance,
        icon: <ThreadIcon weight="bold" className="text-muted size-4" />,
        action: { type: 'mention', mention: { kind: 'thread', target: run.id, label: run.title } },
      })),
      ...paths.slice(0, PATH_LIMIT).map((row): MenuItem => ({
        key: `workspace:${row.path}`,
        group: 'Workspace',
        label: row.path.split('/').at(-1) ?? row.path,
        detail: row.path,
        icon: row.dir ? (
          <FolderIcon weight="bold" className="text-muted size-4" />
        ) : (
          <FileIcon weight="bold" className="text-muted size-4" />
        ),
        action: {
          type: 'mention',
          mention: {
            kind: 'workspace',
            target: row.dir ? `${row.path}/` : row.path,
            label: row.path.split('/').at(-1) ?? row.path,
          },
        },
      })),
    ]
  }, [
    trigger?.char,
    trigger?.command,
    query,
    commands,
    skills,
    paths,
    runs,
    attachments,
    graph,
    runId,
  ])
}

export function ComposerMenu({
  items,
  active,
  onPick,
  onHover,
}: {
  items: MenuItem[]
  active: number
  onPick: (item: MenuItem) => void
  onHover: (index: number) => void
}) {
  const list = useRef<HTMLDivElement>(null)
  useActiveIntoView(list, active)

  return (
    <div
      ref={list}
      role="listbox"
      onMouseDown={(e) => e.preventDefault()}
      className="border-line-strong/70 animate-pop absolute right-0 bottom-full left-0 z-[200] mb-2 max-h-[340px] scrollbar-thin overflow-y-auto rounded-2xl border bg-white p-1.5 shadow-[var(--shadow-large)]"
    >
      {items.map((item, i) => (
        <div key={item.key}>
          {i === 0 || items[i - 1].group !== item.group ? (
            <div className="text-faint px-2.5 pt-1.5 pb-1 text-[11px] font-medium">
              {item.group}
            </div>
          ) : null}
          <button
            type="button"
            role="option"
            data-index={i}
            aria-selected={i === active}
            onMouseMove={() => i !== active && onHover(i)}
            onClick={() => onPick(item)}
            className={cn(
              'flex h-9 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[12.5px]',
              i === active ? 'bg-raised' : '',
            )}
          >
            <span className="flex size-6 shrink-0 items-center justify-center">{item.icon}</span>
            <span className="text-fg shrink-0 truncate font-medium">{item.label}</span>
            {item.detail ? (
              <span className="text-muted min-w-0 flex-1 truncate">{item.detail}</span>
            ) : (
              <span className="flex-1" />
            )}
          </button>
        </div>
      ))}
    </div>
  )
}
