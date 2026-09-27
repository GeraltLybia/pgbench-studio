import { Text } from '@codemirror/state'
import { describe, expect, it } from 'vitest'
import { toCodeMirror } from '@/editor/lint'
import { META_PATTERN, VARIABLE_PATTERN } from '@/editor/pgbenchLanguage'

const DOC = Text.of([
  '\\set aid random(1, 100000 * :scale)',
  'BEGIN;',
  'SELECT abalance FORM pgbench_accounts WHERE aid = :aid;',
])

describe('backend diagnostics -> CodeMirror', () => {
  it('places the marker on the reported line and columns', () => {
    const d = toCodeMirror(DOC, {
      line: 3,
      col: 17,
      end_col: 21,
      severity: 'error',
      message: 'syntax error at or near "pgbench_accounts" · возможно, имелось в виду FROM',
      rule: null,
    })
    expect(DOC.sliceString(d.from, d.to)).toBe('FORM')
    expect(d.severity).toBe('error')
    expect(d.message).toContain('Строка 3, позиция 17')
  })

  it('maps danger and warning levels and clamps out-of-range positions', () => {
    const danger = toCodeMirror(DOC, { line: 2, col: 1, end_col: 6, severity: 'danger', message: 'x', rule: 'r' })
    expect(danger.severity).toBe('warning')
    expect(danger.message.startsWith('Опасно: ')).toBe(true)
    expect(danger.source).toBe('r')
    const warn = toCodeMirror(DOC, { line: 99, col: 500, end_col: 400, severity: 'warning', message: 'x', rule: null })
    expect(warn.severity).toBe('info')
    expect(warn.from).toBeLessThanOrEqual(DOC.length)
    expect(warn.to).toBeGreaterThanOrEqual(warn.from)
  })
})

describe('pgbench highlighting patterns', () => {
  it('matches meta-commands at line start', () => {
    expect('\\set a 1'.match(new RegExp(META_PATTERN.source))?.[0]).toBe('\\set')
    expect('  \\endif'.match(new RegExp(META_PATTERN.source))?.[0]).toBe('  \\endif')
    expect('SELECT 1 \\gset'.match(new RegExp(META_PATTERN.source))).toBeNull()
  })

  it('matches :variables but not ::casts', () => {
    const found = 'SELECT :aid, x::int, f(:scale)'.match(new RegExp(VARIABLE_PATTERN.source, 'g'))
    expect(found).toEqual([':aid', ':scale'])
  })
})
