/**
 * WebSocket of a run: `snapshot` on every (re)connect replaces the state, then live messages.
 * Reconnects with exponential backoff; pings every 30 s so idle proxies keep the connection.
 */
import { onScopeDispose, ref } from 'vue'
import type { RunMessage } from '@/types/events'
import { FINAL_STATUSES } from '@/types/events'

export const PING_MS = 30_000
export const BACKOFF_MS = [1000, 2000, 4000, 8000, 15_000, 30_000]

export type SocketState = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface RunSocketOptions {
  onMessage: (message: RunMessage) => void
  /** For tests. */
  createSocket?: (url: string) => WebSocket
}

export function runSocketUrl(runId: number, location: Location = window.location): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${location.host}/api/runs/${runId}/ws`
}

export function useRunSocket(runId: number, options: RunSocketOptions) {
  const state = ref<SocketState>('connecting')
  const attempts = ref(0)
  let socket: WebSocket | null = null
  let ping: ReturnType<typeof setInterval> | null = null
  let retry: ReturnType<typeof setTimeout> | null = null
  let finished = false
  let stopped = false

  const create = options.createSocket ?? ((url: string) => new WebSocket(url))

  function clearTimers(): void {
    if (ping) clearInterval(ping)
    if (retry) clearTimeout(retry)
    ping = null
    retry = null
  }

  function connect(): void {
    if (stopped) return
    socket = create(runSocketUrl(runId))
    socket.onopen = () => {
      state.value = 'open'
      attempts.value = 0
      ping = setInterval(() => socket?.send(JSON.stringify({ type: 'ping' })), PING_MS)
    }
    socket.onmessage = (event: MessageEvent<string>) => {
      let message: RunMessage
      try {
        message = JSON.parse(event.data) as RunMessage
      } catch {
        return
      }
      if (message.type === 'status' && FINAL_STATUSES.includes(message.status)) finished = true
      if (message.type === 'snapshot' && FINAL_STATUSES.includes(message.status.status)) finished = true
      options.onMessage(message)
    }
    socket.onclose = (event: CloseEvent) => {
      clearTimers()
      socket = null
      // A finished run, or a refusal (4401/4403/4404): no point in reconnecting.
      if (stopped || finished || event.code >= 4400) {
        state.value = 'closed'
        return
      }
      state.value = 'reconnecting'
      const delay = BACKOFF_MS[Math.min(attempts.value, BACKOFF_MS.length - 1)]!
      attempts.value += 1
      retry = setTimeout(connect, delay)
    }
  }

  function close(): void {
    stopped = true
    clearTimers()
    socket?.close(1000)
    state.value = 'closed'
  }

  connect()
  onScopeDispose(close)

  return { state, attempts, close }
}
