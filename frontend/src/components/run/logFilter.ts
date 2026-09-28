import type { LogEvent } from '@/types/events'

export type LogFilter = 'all' | 'progress' | 'errors'

const ERROR = /\b(error|fatal|panic|aborted)\b/i

export function isProgress(line: LogEvent): boolean {
  return line.line.startsWith('progress:')
}

export function isError(line: LogEvent): boolean {
  return ERROR.test(line.line)
}

export function filterLog(lines: LogEvent[], filter: LogFilter): LogEvent[] {
  if (filter === 'progress') return lines.filter(isProgress)
  if (filter === 'errors') return lines.filter(isError)
  return lines
}
