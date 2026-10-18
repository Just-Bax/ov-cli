import {
  ArrowSquareOut as ArrowTopRightOnSquareIcon,
  Check as CheckIcon,
  Copy as Square2StackIcon,
} from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { Button, GithubMark, Shimmer, useCopy } from '@/components/common/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { SECOND_MS } from '@/lib/time'

const SLOW_DOWN_STEP_MS = 5000

export function CopilotSignIn({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState<{ userCode: string; verificationUri: string }>()
  const [error, setError] = useState<string>()
  const [starting, setStarting] = useState(false)
  const [copied, copy] = useCopy()
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const poll = async (deviceCode: string, seconds: number) => {
    let interval = seconds * SECOND_MS
    while (mounted.current) {
      await new Promise((r) => setTimeout(r, interval))
      const res = await api.devicePoll(deviceCode)
      if (res.status === 'ok') return onDone()
      if (res.status === 'error') throw new Error(res.message)
      if (res.status === 'slow_down') interval += SLOW_DOWN_STEP_MS
    }
  }

  const start = async () => {
    setError(undefined)
    setStarting(true)
    try {
      const flow = await api.deviceStart()
      setCode(flow)
      setStarting(false)
      await poll(flow.deviceCode, flow.interval)
    } catch (e) {
      setError((e as Error).message)
      setCode(undefined)
      setStarting(false)
    }
  }

  if (!code)
    return (
      <div>
        <Button
          variant="primary"
          size="lg"
          busy={starting}
          disabled={starting}
          onClick={() => void start()}
        >
          <GithubMark className="size-4" /> Sign in with GitHub
        </Button>
        {error ? <div className="text-danger mt-2 text-[12.5px]">{error}</div> : null}
      </div>
    )

  return (
    <div className="bg-raised rounded-2xl p-4">
      <div className="text-muted text-[12px]">Enter this code on GitHub</div>
      <div className="mt-1.5 flex items-center gap-2">
        <span className="text-fg font-mono text-[26px] font-semibold tracking-[0.16em] select-all">
          {code.userCode}
        </span>
        <button
          type="button"
          aria-label="Copy code"
          onClick={() => copy(code.userCode)}
          className={cn(
            'flex size-9 items-center justify-center rounded-full transition-colors',
            copied ? 'bg-ok-soft text-ok' : 'text-muted hover:text-fg bg-white',
          )}
        >
          {copied ? (
            <CheckIcon className="animate-check size-4" />
          ) : (
            <Square2StackIcon className="size-4" />
          )}
        </button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button
          variant="primary"
          onClick={() => {
            copy(code.userCode)
            window.open(code.verificationUri, '_blank', 'noopener')
          }}
        >
          Copy code and open GitHub <ArrowTopRightOnSquareIcon className="size-3.5" />
        </Button>
        <Shimmer className="text-[12.5px]">Waiting for you to approve</Shimmer>
      </div>
    </div>
  )
}
