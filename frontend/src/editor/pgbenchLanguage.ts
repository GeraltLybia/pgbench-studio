/**
 * pgbench script language for CodeMirror: PostgreSQL SQL plus meta-commands (\set, \if …)
 * and :variables highlighted on top.
 */
import { PostgreSQL, sql } from '@codemirror/lang-sql'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import type { Extension } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from '@codemirror/view'
import { tags } from '@lezer/highlight'

const META = /^[ \t]*\\[A-Za-z]+/g
// :name but not a ::cast
const VARIABLE = /(?<![:\w]):[A-Za-z_][A-Za-z0-9_]*/g

function decorator(regexp: RegExp, className: string): Extension {
  const matcher = new MatchDecorator({ regexp, decoration: Decoration.mark({ class: className }) })
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet
      constructor(view: EditorView) {
        this.decorations = matcher.createDeco(view)
      }
      update(update: ViewUpdate) {
        this.decorations = matcher.updateDeco(update, this.decorations)
      }
    },
    { decorations: (v) => v.decorations },
  )
}

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: 'var(--color-primary-deep)', fontWeight: '600' },
  { tag: [tags.string, tags.special(tags.string)], color: 'var(--color-orange-text)' },
  { tag: [tags.number, tags.bool, tags.null], color: 'var(--color-primary)' },
  { tag: tags.comment, color: 'var(--color-text-muted)', fontStyle: 'italic' },
  { tag: [tags.operator, tags.punctuation], color: 'var(--color-text-muted)' },
])

export const editorTheme = EditorView.theme({
  '&': {
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    backgroundColor: 'var(--color-surface)',
    color: 'var(--color-text)',
  },
  '.cm-content': { fontFamily: 'var(--font-mono)', padding: '12px 0', caretColor: 'var(--color-primary)' },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '1.75' },
  '.cm-gutters': {
    backgroundColor: 'var(--color-surface)',
    color: 'var(--color-text-muted)',
    border: 'none',
  },
  '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--color-selected)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-pgb-meta': { color: 'var(--color-primary)', fontWeight: '600' },
  '.cm-pgb-var': { color: 'var(--color-var)' },
  '.cm-tooltip': {
    border: 'none',
    borderRadius: '10px',
    backgroundColor: 'var(--color-code-bg)',
    color: 'var(--color-code-text)',
  },
  '.cm-diagnostic': { padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '13px' },
  '.cm-diagnostic-error': { borderLeft: '3px solid var(--color-orange)' },
  '.cm-diagnostic-warning': { borderLeft: '3px solid var(--color-orange)' },
  '.cm-diagnostic-info': { borderLeft: '3px solid var(--color-primary)' },
  '.cm-lintRange-error': {
    backgroundImage: 'none',
    textDecoration: 'underline wavy var(--color-orange)',
    textUnderlineOffset: '3px',
  },
  '.cm-lintRange-warning': {
    backgroundImage: 'none',
    textDecoration: 'underline wavy var(--color-orange)',
    textUnderlineOffset: '3px',
  },
  '.cm-lintRange-info': {
    backgroundImage: 'none',
    textDecoration: 'underline dotted var(--color-primary)',
    textUnderlineOffset: '3px',
  },
})

export function pgbenchLanguage(): Extension {
  return [
    sql({ dialect: PostgreSQL, upperCaseKeywords: true }),
    syntaxHighlighting(highlight),
    decorator(META, 'cm-pgb-meta'),
    decorator(VARIABLE, 'cm-pgb-var'),
  ]
}

export { META as META_PATTERN, VARIABLE as VARIABLE_PATTERN }
