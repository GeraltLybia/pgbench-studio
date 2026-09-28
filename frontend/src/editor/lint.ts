/** Backend diagnostics (/api/scripts/validate) -> CodeMirror lint markers. */
import { linter, type Diagnostic } from '@codemirror/lint'
import type { Text } from '@codemirror/state'
import type { Extension } from '@codemirror/state'
import type { ScriptDiagnostic } from '@/api/scripts'

/** Debounce of the lint request after the last edit (docs/architecture.md, «Редактор»). */
export const LINT_DELAY_MS = 400

const SEVERITY: Record<ScriptDiagnostic['severity'], Diagnostic['severity']> = {
  error: 'error',
  danger: 'warning',
  warning: 'info',
}

const PREFIX: Record<ScriptDiagnostic['severity'], string> = {
  error: '',
  danger: 'Опасно: ',
  warning: 'Внимание: ',
}

export function toCodeMirror(doc: Text, d: ScriptDiagnostic): Diagnostic {
  const line = doc.line(Math.min(Math.max(d.line, 1), doc.lines))
  const from = line.from + Math.min(Math.max(d.col - 1, 0), line.length)
  let to = line.from + Math.min(Math.max(d.end_col - 1, 0), line.length)
  if (to <= from) to = Math.min(from + 1, line.to)
  return {
    from,
    to: Math.max(to, from),
    severity: SEVERITY[d.severity],
    message: `${PREFIX[d.severity]}${d.message}\nСтрока ${d.line}, позиция ${d.col}`,
    source: d.rule ?? undefined,
  }
}

/** `check` returns diagnostics for exactly this text (the store deduplicates requests). */
export function pgbenchLinter(
  check: (text: string) => Promise<ScriptDiagnostic[] | null>,
): Extension {
  return linter(
    async (view) => {
      const doc = view.state.doc
      const diagnostics = await check(doc.toString())
      if (diagnostics === null || view.state.doc !== doc) return []
      return diagnostics.map((d) => toCodeMirror(doc, d))
    },
    { delay: LINT_DELAY_MS },
  )
}
