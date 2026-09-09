import axios from 'axios'
import * as fx from './fixtures'
import type {
  CaseDetail, CaseList, ChatReply, EntitySearch, EvalResult, Golden,
  ChatMessage, Health, RuleChunk, ScreeningResult, Stats, StreamEvent, SuggestedQuestion,
} from './types'

/**
 * Where the API lives.
 *
 * Explicit config wins. Otherwise talk to the same host that served this page
 * on the API port — so opening the app from another device on the network
 * reaches that machine's backend rather than the visitor's own localhost.
 */
const API_PORT = 8000
const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:${API_PORT}/api/v1`
export const MOCK_MODE = import.meta.env.VITE_MOCK_MODE === 'true'
export const POLL_INTERVAL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS ?? 2000)

const http = axios.create({ baseURL: BASE_URL, timeout: 120000 })

/** SSE frames are terminated by a blank line. */
const SSE_FRAME_SEPARATOR = '\n\n'

const mock = <T,>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), 250))

export const api = {
  getHealth: (): Promise<Health> =>
    MOCK_MODE ? mock(fx.fixtureHealth) : http.get('/health').then((r) => r.data),

  getStats: (): Promise<Stats> =>
    MOCK_MODE ? mock(fx.fixtureStats) : http.get('/stats').then((r) => r.data),

  listCases: (): Promise<CaseList> =>
    MOCK_MODE ? mock(fx.fixtureCaseList) : http.get('/cases').then((r) => r.data),

  getCase: (caseId: string): Promise<CaseDetail> =>
    MOCK_MODE ? mock(fx.fixtureCaseDetail) : http.get(`/cases/${caseId}`).then((r) => r.data),

  createCase: (payload: unknown): Promise<CaseDetail> =>
    MOCK_MODE ? mock(fx.fixtureCaseDetail) : http.post('/cases', payload).then((r) => r.data),

  startScreening: (caseId: string): Promise<{ screening_id: string; status: string }> =>
    MOCK_MODE
      ? mock({ screening_id: fx.fixtureScreening.screening_id, status: 'PENDING' })
      : http.post(`/cases/${caseId}/screen`).then((r) => r.data),

  getScreening: (screeningId: string): Promise<ScreeningResult> =>
    MOCK_MODE ? mock(fx.fixtureScreening) : http.get(`/screenings/${screeningId}`).then((r) => r.data),

  listScreenings: (caseId: string): Promise<ScreeningResult[]> =>
    MOCK_MODE ? mock([fx.fixtureScreening]) : http.get(`/cases/${caseId}/screenings`).then((r) => r.data),

  getGolden: (caseId: string): Promise<Golden> =>
    MOCK_MODE ? mock(fx.fixtureGolden) : http.get(`/cases/${caseId}/golden`).then((r) => r.data),

  evaluate: (caseId: string): Promise<EvalResult> =>
    MOCK_MODE ? mock(fx.fixtureEval) : http.post(`/cases/${caseId}/evaluate`).then((r) => r.data),

  searchEntities: (q: string, threshold = 0.8): Promise<EntitySearch> =>
    MOCK_MODE
      ? mock(fx.fixtureSearch)
      : http.get('/search/entities', { params: { q, threshold } }).then((r) => r.data),

  listRules: (): Promise<RuleChunk[]> =>
    MOCK_MODE
      ? mock(fx.fixtureRules)
      : http.get('/rules').then((r) => r.data.results),

  getChatMessages: (sessionId: string): Promise<ChatMessage[]> =>
    MOCK_MODE ? mock([]) : http.get(`/chat/${sessionId}/messages`).then((r) => r.data),

  getSuggestions: (): Promise<SuggestedQuestion[]> =>
    MOCK_MODE
      ? mock([
          { category: 'Screening', question: 'Are there any conflicts for KDDI (Thailand) Limited?' },
          { category: 'Engagement team', question: 'Can we staff Soon Bee Koh on a new KDDI job?' },
        ])
      : http.get('/chat/suggestions').then((r) => r.data),

  /**
   * Streamed chat. A screening question takes 40-120s on a local model, so the
   * caller gets tool calls and answer tokens as they happen. EventSource can't
   * POST, so the SSE frames are parsed off a fetch body reader.
   */
  chatStream: async (
    message: string,
    caseId: string | null,
    sessionId: string | null,
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    if (MOCK_MODE) {
      const reply = fx.fixtureChat.reply
      onEvent({ type: 'tool_call', tool: 'search_rules', args: { query: message } })
      for (const word of reply.split(' ')) {
        await new Promise((r) => setTimeout(r, 20))
        onEvent({ type: 'token', text: word + ' ' })
      }
      onEvent({ type: 'done', ...fx.fixtureChat, seconds: 1 } as StreamEvent)
      return
    }

    const response = await fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, case_id: caseId, session_id: sessionId }),
      signal,
    })
    if (!response.ok || !response.body) throw new Error(`stream failed: ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE frames are separated by a blank line
      const frames = buffer.split(SSE_FRAME_SEPARATOR)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const line = frame.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        try {
          onEvent(JSON.parse(line.slice(6)) as StreamEvent)
        } catch {
          // a partial frame; the next read will complete it
        }
      }
    }
  },

  chat: (message: string, caseId: string | null, sessionId: string | null): Promise<ChatReply> =>
    MOCK_MODE
      ? mock(fx.fixtureChat)
      : http.post('/chat', { message, case_id: caseId, session_id: sessionId }).then((r) => r.data),
}
