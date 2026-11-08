import { ShieldWarning as ShieldWarningIcon } from '@phosphor-icons/react'
import { memo } from 'react'
import type { RunState } from '@shared/types.ts'
import { Markdown } from '@/components/common/ui'
import { Reasoning } from '@/components/run/Reasoning'
import { ChangeCard } from './ChangeCard'
import { CompactionNote } from './Context'
import { GridCard } from './GridCard'
import { Answer, LoginCard } from './Panels'
import { AnsweredQuestion } from './QuestionDock'
import { ToolGroup } from './ToolGroup'
import {
  type Block,
  browserQuestion,
  changeById,
  chatById,
  isOpen,
  LIVE_QUESTION,
} from './threadTurns'

const MemoChangeCard = memo(ChangeCard)
const MemoGridCard = memo(GridCard)
const MemoAnswer = memo(Answer)

export function ThreadBlock({
  block,
  state,
  inherited,
}: {
  block: Block
  state: RunState
  inherited: boolean
}) {
  if (block.kind === 'tools') return <ToolGroup runId={state.summary.id} tools={block.tools} />

  const { item } = block
  const id = state.summary.id
  switch (item.kind) {
    case 'text': {
      const msg = chatById(state).get(item.id)
      const said = msg?.text.trim()
      const thought = msg?.reasoning?.trim()
      if (!msg || (!said && !thought)) return null

      return (
        <div className="text-fg space-y-2">
          {thought ? <Reasoning text={thought} /> : null}
          {said ? <Markdown text={msg.text} links={msg.links} /> : null}
        </div>
      )
    }
    case 'change': {
      const change = changeById(state).get(item.id)
      return change ? <MemoChangeCard change={change} /> : null
    }
    case 'grid': {
      const grid = state.grids.find((g) => g.id === item.id)
      return grid ? <MemoGridCard grid={grid} runId={id} inherited={inherited} /> : null
    }
    case 'question': {
      const q = state.questions.find((x) => x.id === item.id)
      if (!q) return null

      const live = LIVE_QUESTION.has(state.summary.status)
      if (!isOpen(q) || !live) return <AnsweredQuestion question={q} />

      return (
        <div className="text-warn flex items-center gap-2 text-[12.5px] font-medium">
          <ShieldWarningIcon className="size-4" />
          {q.id === browserQuestion(state)?.id
            ? 'Waiting for your approval in the browser'
            : q.kind === 'approval'
              ? 'Waiting for your approval below'
              : 'Waiting for your answer below'}
        </div>
      )
    }
    case 'login': {
      const l = state.logins.find((x) => x.id === item.id)
      return l ? <LoginCard runId={id} login={l} /> : null
    }
    case 'outcome':
      if (item.id !== state.outcomeId || !state.outcome) {
        return <div className="text-faint text-[12px]">Earlier answer, updated below.</div>
      }

      return <MemoAnswer outcome={state.outcome} caseUrl={state.caseUrl} />
    case 'compact': {
      const compaction = state.compactions.find((c) => c.id === item.id)
      return compaction ? <CompactionNote compaction={compaction} /> : null
    }
  }
}
