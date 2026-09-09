import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Bot, ChevronDown, ChevronRight, RotateCcw, Send, Square, User, Wrench } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { AgentTrace, StreamEvent } from '../api/types'
import { Card, RuleChip } from '../components/ui'
import { Markdown } from '../components/Markdown'

interface LiveStep {
  tool: string
  args: Record<string, unknown>
  summary?: string
}

interface Turn {
  role: 'user' | 'assistant'
  content: string
  trace?: AgentTrace[]
  steps?: LiveStep[]
  citations?: { slide_number: number; title: string | null }[]
  seconds?: number
  streaming?: boolean
}

function argSummary(args: Record<string, unknown>): string {
  return Object.values(args)
    .map((v) => (typeof v === 'string' ? v : JSON.stringify(v)))
    .filter(Boolean)
    .join(', ')
    .slice(0, 70)
}

/** What the agent is doing right now — the reason streaming exists. */
function LiveSteps({ steps, status }: { steps: LiveStep[]; status: string | null }) {
  if (!steps.length && !status) return null
  return (
    <div className="mb-2 space-y-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center gap-1.5 font-mono text-[11px] text-slate-600">
          <Wrench className={clsx('h-3 w-3', !s.summary && 'animate-pulse text-sky-500')} />
          <span className="font-semibold">{s.tool}</span>
          <span className="text-slate-400">({argSummary(s.args)})</span>
          {s.summary && <span className="text-emerald-700">→ {s.summary}</span>}
        </div>
      ))}
      {status && <p className="text-[11px] italic text-slate-400">{status}</p>}
    </div>
  )
}

function TracePanel({ trace }: { trace: AgentTrace[] }) {
  const [open, setOpen] = useState(false)
  if (!trace.length) return null
  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-semibold text-slate-600"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        Agent trace ({trace.reduce((n, t) => n + (t.tool_calls?.length ?? 0), 0)} tool calls)
      </button>
      {open && (
        <ol className="space-y-2 border-t border-slate-200 px-3 py-2">
          {trace.map((t, i) => (
            <li key={i} className="text-xs">
              <div className="flex items-center gap-1.5">
                <span className="rounded bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white">
                  {t.agent}
                </span>
                <span className="text-slate-600">{t.summary}</span>
              </div>
              {t.tool_calls?.length > 0 && (
                <ul className="ml-3 mt-1 space-y-0.5">
                  {t.tool_calls.map((tc, j) => (
                    <li key={j} className="font-mono text-[11px] text-slate-500">
                      <Wrench className="mr-1 inline h-3 w-3" />
                      {tc.tool}({argSummary((tc.args ?? {}) as Record<string, unknown>)})
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/** Conversations are persisted server-side; this remembers which one we're in
 *  so a refresh rejoins it instead of silently starting a new thread. */
const sessionKey = (caseId: string | null) => `conflict-chat-session:${caseId ?? 'global'}`

export default function Chat() {
  const { caseId = null } = useParams()
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem(sessionKey(caseId)),
  )
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [steps, setSteps] = useState<LiveStep[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const suggestions = useQuery({ queryKey: ['suggestions'], queryFn: api.getSuggestions })

  // Rehydrate the visible conversation from the database on mount. The rows
  // were always being written; nothing was reading them back, so a refresh
  // looked like the history had been lost.
  useEffect(() => {
    const stored = localStorage.getItem(sessionKey(caseId))
    if (!stored) return
    let cancelled = false
    setRestoring(true)
    api
      .getChatMessages(stored)
      .then((messages) => {
        if (cancelled) return
        setTurns(
          messages
            .filter((m) => m.role === 'user' || m.role === 'assistant')
            .map((m) => ({
              role: m.role as 'user' | 'assistant',
              content: m.content,
              trace: m.role === 'assistant' ? m.tool_calls : undefined,
            })),
        )
      })
      .catch(() => {
        // session no longer exists (e.g. the database was reloaded)
        localStorage.removeItem(sessionKey(caseId))
        setSessionId(null)
      })
      .finally(() => !cancelled && setRestoring(false))
    return () => {
      cancelled = true
    }
  }, [caseId])

  const rememberSession = (id: string) => {
    setSessionId(id)
    localStorage.setItem(sessionKey(caseId), id)
  }

  const newConversation = () => {
    localStorage.removeItem(sessionKey(caseId))
    setSessionId(null)
    setTurns([])
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, steps])

  const send = async (message: string) => {
    if (!message.trim() || busy) return
    setTurns((prev) => [...prev, { role: 'user', content: message }])
    setInput('')
    setBusy(true)
    setSteps([])
    setStatus(null)

    const controller = new AbortController()
    abortRef.current = controller
    const liveSteps: LiveStep[] = []

    setTurns((prev) => [...prev, { role: 'assistant', content: '', streaming: true }])

    const patchLast = (patch: Partial<Turn>) =>
      setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, ...patch } : t)))

    try {
      await api.chatStream(message, caseId, sessionId, (event: StreamEvent) => {
        switch (event.type) {
          case 'session':
            rememberSession(event.session_id)
            break
          case 'status':
            setStatus(event.message)
            break
          case 'tool_call':
            liveSteps.push({ tool: event.tool, args: event.args })
            setSteps([...liveSteps])
            break
          case 'tool_result': {
            const step = [...liveSteps].reverse().find((s) => s.tool === event.tool && !s.summary)
            if (step) step.summary = event.summary
            setSteps([...liveSteps])
            break
          }
          case 'token':
            setStatus(null)
            setTurns((prev) =>
              prev.map((t, i) => (i === prev.length - 1 ? { ...t, content: t.content + event.text } : t)),
            )
            break
          case 'error':
            patchLast({ content: event.message, streaming: false })
            break
          case 'done':
            rememberSession(event.session_id)
            patchLast({
              content: event.reply,
              trace: event.agent_trace,
              citations: event.citations,
              seconds: event.seconds,
              steps: liveSteps,
              streaming: false,
            })
            break
        }
      }, controller.signal)
    } catch (err) {
      if (!controller.signal.aborted) {
        patchLast({ content: `Something went wrong: ${String(err)}`, streaming: false })
      }
    } finally {
      setBusy(false)
      setSteps([])
      setStatus(null)
      abortRef.current = null
    }
  }

  const grouped = (suggestions.data ?? []).reduce<Record<string, string[]>>((acc, s) => {
    (acc[s.category] ||= []).push(s.question)
    return acc
  }, {})

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Ask the assistant</h1>
          <p className="text-sm text-slate-500">
            {caseId ? 'Scoped to this case. ' : ''}
            It answers by running the checks — searching the databases and applying the QRC —
            not by describing the process. A screening question takes a minute or two.
          </p>
        </div>
        {turns.length > 0 && (
          <div className="flex items-center gap-3">
            {sessionId && (
              <span className="text-xs text-slate-400">
                conversation {sessionId.slice(0, 8)} · saved
              </span>
            )}
            <button
              onClick={newConversation}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
            >
              <RotateCcw className="h-3.5 w-3.5" /> New conversation
            </button>
          </div>
        )}
      </div>

      {turns.length === 0 && !restoring && (
        <Card title="Try one of these">
          <div className="space-y-4">
            {Object.entries(grouped).map(([category, questions]) => (
              <div key={category}>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {category}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {questions.map((q) => (
                    <button
                      key={q}
                      onClick={() => send(q)}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs text-slate-700 transition hover:border-deloitte-green hover:bg-slate-50"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {suggestions.isLoading && <p className="text-sm text-slate-400">Loading suggestions…</p>}
          </div>
        </Card>
      )}

      <Card>
        <div className="max-h-[34rem] space-y-5 overflow-y-auto">
          {restoring && <p className="text-sm text-slate-400">Restoring conversation…</p>}
          {turns.map((t, i) => (
            <div key={i} className="flex gap-2.5">
              <div
                className={clsx(
                  'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full',
                  t.role === 'user' ? 'bg-slate-200' : 'bg-deloitte-green/25',
                )}
              >
                {t.role === 'user' ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </div>
              <div className="min-w-0 flex-1">
                {t.role === 'user' ? (
                  <p className="text-sm font-medium text-slate-800">{t.content}</p>
                ) : (
                  <>
                    {t.streaming && <LiveSteps steps={steps} status={status} />}
                    {!t.streaming && t.steps && t.steps.length > 0 && (
                      <LiveSteps steps={t.steps} status={null} />
                    )}
                    {t.content ? (
                      <Markdown>{t.content}</Markdown>
                    ) : (
                      t.streaming && <span className="text-sm text-slate-400">…</span>
                    )}
                    {t.streaming && t.content && (
                      <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-slate-400 align-text-bottom" />
                    )}
                    {t.citations && t.citations.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {t.citations.map((c, j) => (
                          <RuleChip
                            key={j}
                            citation={`QRC slide ${c.slide_number}${c.title ? ` — ${c.title}` : ''}`}
                          />
                        ))}
                      </div>
                    )}
                    {t.seconds !== undefined && (
                      <p className="mt-1 text-[11px] text-slate-400">answered in {t.seconds}s</p>
                    )}
                    {t.trace && <TracePanel trace={t.trace} />}
                  </>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
          className="mt-4 flex gap-2 border-t border-slate-100 pt-4"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. Can we take on tax advisory work for KDDI Corporation?"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50"
            >
              <Square className="h-3.5 w-3.5" /> Stop
            </button>
          ) : (
            <button
              type="submit"
              className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
            >
              <Send className="h-4 w-4" /> Send
            </button>
          )}
        </form>
      </Card>
    </div>
  )
}
