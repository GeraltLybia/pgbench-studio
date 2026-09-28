from __future__ import annotations

import pytest

from app.core.validator import (
    Diagnostic,
    split_commands,
    substitute_variables,
    validate_script,
)

MOCKUP_SCRIPT = """\\set aid random(1, 100000 * :scale)
\\set delta random(-5000, 5000)
BEGIN;
SELECT abalance FORM pgbench_accounts WHERE aid = :aid;
UPDATE pgbench_accounts SET abalance = abalance + :delta WHERE aid = :aid;
END;
"""


def diags(text: str, **kwargs: object) -> list[Diagnostic]:
    return validate_script(text, **kwargs).diagnostics  # type: ignore[arg-type]


def only(text: str, severity: str, **kwargs: object) -> list[Diagnostic]:
    return [d for d in diags(text, **kwargs) if d.severity == severity]


# --- splitting -----------------------------------------------------------------------------


def test_split_meta_and_sql() -> None:
    cmds = split_commands("\\set a 1\nSELECT 1;\nSELECT\n  2 ;  \\sleep 1 ms\n")
    assert [(c.kind, c.name) for c in cmds] == [
        ("meta", "set"),
        ("sql", ""),
        ("sql", ""),
        ("meta", "sleep"),
    ]
    assert cmds[0].args == ["a", "1"]
    assert cmds[2].text == "SELECT\n  2 ;"


def test_split_respects_quotes_comments_and_dollar_quotes() -> None:
    text = (
        "SELECT ';' , \"a;b\", $$x;y$$, $f$\\z;$f$ /* c; \\d */ -- e; \\f\n"
        "  FROM t;\nSELECT E'it\\'s;';"
    )
    cmds = split_commands(text)
    assert [c.kind for c in cmds] == ["sql", "sql"]
    assert cmds[0].text.endswith("FROM t;")


def test_gset_ends_sql_without_semicolon() -> None:
    cmds = split_commands("SELECT 1 AS a \\gset p_\nSELECT :p_a;")
    assert [(c.kind, c.name) for c in cmds] == [("sql", ""), ("meta", "gset"), ("sql", "")]
    assert cmds[0].open_ended


def test_meta_line_continuation() -> None:
    cmds = split_commands("\\set x \\\n  1 + 2\nSELECT :x;")
    assert cmds[0].args == ["x", "1", "+", "2"]
    assert cmds[1].kind == "sql"


def test_substitution_keeps_offsets_and_skips_casts_and_strings() -> None:
    sql = "SELECT :aid, x::int, ':b', \"c:d\" /* :e */ FROM t WHERE y = :y;"
    out, used = substitute_variables(sql)
    assert len(out) == len(sql)
    assert [name for name, _ in used] == ["aid", "y"]
    assert "::int" in out and "':b'" in out and ":e" in out
    assert out[used[0][1] : used[0][1] + 4] == "0   "


# --- SQL errors ----------------------------------------------------------------------------


def test_mockup_syntax_error_on_the_right_line_with_hint() -> None:
    errors = only(MOCKUP_SCRIPT, "error", server_major=16)
    assert len(errors) == 1
    e = errors[0]
    assert (e.line, e.col, e.end_col) == (4, 17, 21)  # «FORM»
    assert "syntax error" in e.message
    assert "возможно, имелось в виду FROM" in e.message


def test_syntax_error_position_in_multiline_command() -> None:
    text = "\\set a 1\nSELECT a,\n       b\n  FROMM t\n  WHERE;"
    errors = only(text, "error")
    assert len(errors) == 1
    assert errors[0].line == 5 or errors[0].line == 4


def test_valid_mockup_after_fix_has_no_errors() -> None:
    fixed = MOCKUP_SCRIPT.replace("FORM", "FROM")
    result = validate_script(fixed, 16)
    assert not result.has_errors
    assert result.diagnostics == []
    assert result.variables_used == ["aid", "delta", "scale"]
    assert result.variables_defined == ["aid", "delta"]


# --- meta-commands -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("\\foo 1", "Неизвестная мета-команда \\foo"),
        ("\\set x", "неверное число аргументов"),
        ("\\set 1x 2", "некорректное имя переменной"),
        ("\\sleep", "неверное число аргументов"),
        ("\\sleep abc", "ожидается число"),
        ("\\sleep 1 min", "единица должна быть"),
        ("\\else", "\\else без \\if"),
        ("\\elif 1", "\\elif без \\if"),
        ("\\endif", "\\endif без \\if"),
        ("\\if 1\n\\else\n\\else\n\\endif", "\\else после \\else"),
        ("\\if 1\n\\else\n\\elif 2\n\\endif", "\\elif после \\else"),
        ("\\if 1\nSELECT 1;", "Незакрытый \\if"),
        ("\\gset", "должен следовать за SQL-командой"),
        ("\\set a 1\n\\aset", "должен следовать за SQL-командой"),
        ("\\endpipeline x", "неверное число аргументов"),
    ],
)
def test_meta_errors(text: str, fragment: str) -> None:
    errors = only(text, "error")
    assert any(fragment in e.message for e in errors), errors


def test_meta_ok() -> None:
    text = (
        "\\set a random(1, 10)\n\\sleep 5 ms\n\\sleep :a\n\\if :a > 5\nSELECT 1;\n"
        "\\elif :a > 2\nSELECT 2;\n\\else\nSELECT 3;\n\\endif\n"
        "\\startpipeline\nSELECT 4;\n\\syncpipeline\nSELECT 5;\n\\endpipeline\n"
    )
    assert only(text, "error") == []


@pytest.mark.parametrize("name", ["shell", "setshell"])
def test_shell_is_forbidden(name: str) -> None:
    errors = only(f"\\{name} x ls -la", "error")
    assert errors[0].rule == name
    assert "запрещён" in errors[0].message


def test_unknown_variable_is_a_warning() -> None:
    warnings = only("SELECT :nosuch;", "warning")
    assert len(warnings) == 1
    assert (warnings[0].line, warnings[0].col) == (1, 8)
    assert "-D" in warnings[0].message
    assert only("SELECT :nosuch;", "warning", defined_variables=frozenset({"nosuch"})) == []
    assert only("SELECT :scale, :client_id, :random_seed;", "warning") == []


def test_gset_defines_result_columns_with_prefix() -> None:
    text = "SELECT abalance, 1 AS n FROM pgbench_accounts \\gset p_\nSELECT :p_abalance, :p_n;"
    assert only(text, "warning") == []
    # Unknown column names: anything with the prefix is accepted.
    assert only("SELECT count(*) \\gset q_\nSELECT :q_whatever;", "warning") == []
    assert only("SELECT 1 AS a \\aset\nSELECT :a;", "warning") == []


# --- dangerous constructs ------------------------------------------------------------------

FORBIDDEN = [
    ("DROP DATABASE bench;", "drop_database"),
    ("DROP ROLE r;", "drop_role"),
    ("ALTER SYSTEM SET work_mem = '1GB';", "alter_system"),
    ("CREATE ROLE r;", "create_role"),
    ("ALTER ROLE r SUPERUSER;", "alter_role"),
    ("ALTER ROLE r SET work_mem = 1;", "alter_role"),
    ("SELECT pg_terminate_backend(1);", "pg_terminate_backend"),
    ("SELECT pg_catalog.pg_cancel_backend(1);", "pg_cancel_backend"),
    ("SELECT pg_reload_conf();", "pg_reload_conf"),
    ("COPY pgbench_history TO PROGRAM 'cat';", "copy_program"),
    ("COPY pgbench_history FROM PROGRAM 'cat';", "copy_program"),
]

DANGER = [
    ("DROP TABLE pgbench_history;", "drop_table"),
    ("TRUNCATE pgbench_history;", "truncate"),
    ("ALTER TABLE pgbench_history ADD COLUMN x int;", "alter_table"),
    ("VACUUM FULL pgbench_history;", "vacuum_full"),
    ("CLUSTER pgbench_accounts;", "cluster"),
    ("REINDEX TABLE pgbench_accounts;", "reindex"),
    ("DELETE FROM pgbench_history;", "delete_without_where"),
    ("UPDATE pgbench_accounts SET abalance = 0;", "update_without_where"),
    ("LOCK TABLE pgbench_accounts;", "lock_table"),
]


@pytest.mark.parametrize(("sql", "rule"), FORBIDDEN)
def test_forbidden(sql: str, rule: str) -> None:
    found = [d for d in diags(sql) if d.rule == rule]
    assert found and found[0].severity == "error", diags(sql)


@pytest.mark.parametrize(("sql", "rule"), DANGER)
def test_danger(sql: str, rule: str) -> None:
    found = [d for d in diags(sql) if d.rule == rule]
    assert found and found[0].severity == "danger", diags(sql)
    assert found[0].line == 1


def test_safe_variants_are_not_flagged() -> None:
    text = (
        "VACUUM pgbench_history;\n"
        "DELETE FROM pgbench_history WHERE tid = 1;\n"
        "UPDATE pgbench_accounts SET abalance = 0 WHERE aid = 1;\n"
        "COPY pgbench_history TO STDOUT;\n"
        "SELECT 'DROP TABLE x; TRUNCATE y' -- DROP DATABASE z\n;\n"
        "/* ALTER SYSTEM SET x = 1 */ SELECT 1;\n"
    )
    assert diags(text) == []


def test_attention_for_foreign_tables_and_open_transaction() -> None:
    warnings = only("BEGIN;\nINSERT INTO orders VALUES (1);\n", "warning")
    rules = {w.rule for w in warnings}
    assert rules == {"write_non_pgbench", "begin_without_end"}
    assert only("BEGIN;\nSELECT 1;\nEND;\nSTART TRANSACTION;\nROLLBACK;", "warning") == []


def test_danger_marker_points_at_the_statement() -> None:
    found = diags("SELECT 1;\n  DELETE FROM pgbench_history;")
    d = next(x for x in found if x.severity == "danger")
    assert (d.line, d.col, d.end_col) == (2, 3, 9)


# --- server version ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "too_old", "ok"),
    [
        (
            "MERGE INTO pgbench_accounts a USING pgbench_branches b ON a.bid = b.bid "
            "WHEN MATCHED THEN DO NOTHING;",
            14,
            15,
        ),
        ("SELECT '{}' IS JSON;", 15, 16),
        ("SELECT JSON_OBJECT('a': 1);", 15, 16),
        ("SELECT * FROM JSON_TABLE('[]', '$[*]' COLUMNS (a int PATH '$.a')) t;", 16, 17),
        ("SELECT JSON_QUERY('{}', '$.a');", 16, 17),
        (
            "MERGE INTO pgbench_accounts a USING pgbench_branches b ON a.bid = b.bid "
            "WHEN MATCHED THEN DO NOTHING RETURNING 1;",
            16,
            17,
        ),
    ],
)
def test_version_specific_syntax(sql: str, too_old: int, ok: int) -> None:
    errors = [d for d in diags(sql, server_major=too_old) if d.rule == "server_version"]
    assert errors and f"PostgreSQL {too_old}" in errors[0].message
    assert [d for d in diags(sql, server_major=ok) if d.rule == "server_version"] == []
    # Unknown server version: no version errors, the dry run will tell.
    assert [d for d in diags(sql) if d.rule == "server_version"] == []


def test_empty_script() -> None:
    result = validate_script("   \n-- only a comment\n")
    assert result.diagnostics == []
