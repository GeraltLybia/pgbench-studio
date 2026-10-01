import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  LogEvent,
  ProgressEvent,
  ResourcesEvent,
  RunInfo,
  RunMessage,
  StatusEvent,
  WarningEvent,
} from '@/types/events'
import { FINAL_STATUSES } from '@/types/events'

/** Log lines kept in the browser (согласно документации, «Состояние»). */
export const LOG_BUFFER = 5000

/** One store per run id: the state of its WebSocket. */
export function useRunStore(runId: number) {
  return defineStore(`run-${runId}`, () => {
    const status = ref<StatusEvent | null>(null)
    const info = ref<RunInfo | null>(null)
    const log = ref<LogEvent[]>([])
    const progress = ref<ProgressEvent[]>([])
    const resources = ref<ResourcesEvent[]>([])
    const warnings = ref<WarningEvent[]>([])
    /** When the last progress point arrived (for the local countdown between points). */
    const lastProgressAt = ref<number | null>(null)

    const finished = computed(
      () => status.value !== null && FINAL_STATUSES.includes(status.value.status),
    )
    const last = computed(() => progress.value.at(-1) ?? null)
    const lastResources = computed(() => resources.value.at(-1) ?? null)

    function pushLog(line: LogEvent): void {
      log.value.push(line)
      if (log.value.length > LOG_BUFFER) log.value.splice(0, log.value.length - LOG_BUFFER)
    }

    function apply(message: RunMessage, now = Date.now()): void {
      switch (message.type) {
        case 'snapshot':
          status.value = message.status.status ? message.status : null
          info.value = message.config
          log.value = message.log.slice(-LOG_BUFFER)
          progress.value = [...message.progress]
          resources.value = [...message.resources]
          warnings.value = [...message.warnings]
          lastProgressAt.value = message.progress.length ? now : null
          break
        case 'log':
          pushLog(message)
          break
        case 'progress':
          progress.value.push(message)
          lastProgressAt.value = now
          break
        case 'resources':
          resources.value.push(message)
          break
        case 'warning':
          warnings.value.push(message)
          break
        case 'status':
          status.value = message
          break
        case 'pong':
          break
      }
    }

    return { status, info, log, progress, resources, warnings, lastProgressAt, finished, last, lastResources, apply }
  })()
}
