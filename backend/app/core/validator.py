"""pgbench script validator: meta-commands, SQL via pglast, dangerous rules, server version.

Diagnostics carry 1-based line and column of the original text, so the editor can place
markers. Severities: error (blocks the run), danger (needs confirmation), warning (marker).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pglast import parse_sql
from pglast.parser import ParseError

from app.core import safety

Severity = Literal["error", "danger", "warning"]
CommandKind = Literal["meta", "sql"]

# Variables pgbench defines by itself.
AUTOMATIC_VARIABLES = frozenset({"scale", "client_id", "random_seed", "default_seed"})

# name -> (min args, max args or None); \shell and \setshell are handled separately.
META_COMMANDS: dict[str, tuple[int, int | None]] = {
    "set": (2, None),
    "sleep": (1, 2),
    "if": (1, None),
    "elif": (1, None),
    "else": (0, 0),
    "endif": (0, 0),
    "gset": (0, 1),
    "aset": (0, 1),
    "startpipeline": (0, 0),
    "syncpipeline": (0, 0),
    "endpipeline": (0, 0),
}
FORBIDDEN_META = frozenset({"shell", "setshell"})
SLEEP_UNITS = frozenset({"us", "ms", "s"})

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VAR_RE = re.compile(r":([A-Za-z0-9_]+)")
_NEAR_RE = re.compile(r'at or near "([^"]*)"')
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")

LEVEL_SEVERITY: dict[safety.Level, Severity] = {
    "forbidden": "error",
    "danger": "danger",
    "attention": "warning",
}

SQL_KEYWORDS = [
    "SELECT",
    "FROM",
    "WHERE",
    "INSERT",
    "INTO",
    "VALUES",
    "UPDATE",
    "SET",
    "DELETE",
    "BEGIN",
    "END",
    "COMMIT",
    "ROLLBACK",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "ON",
    "GROUP",
    "ORDER",
    "BY",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "RETURNING",
    "AND",
    "OR",
    "NOT",
    "NULL",
    "AS",
    "DISTINCT",
    "UNION",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "WITH",
    "TABLE",
    "CREATE",
    "ALTER",
    "DROP",
]


class _AddFn(Protocol):
    """Collector of diagnostics passed to the checks."""

    def __call__(
        self, start: int, end: int, severity: Severity, message: str, rule: str | None = ...
    ) -> None: ...


@dataclass(frozen=True)
class Diagnostic:
    line: int
    col: int
    end_col: int
    severity: Severity
    message: str
    rule: str | None = None


@dataclass
class Command:
    kind: CommandKind
    start: int
    end: int
    text: str
    name: str = ""
    args: list[str] = field(default_factory=list)
    # SQL ended by a meta-command such as \gset instead of a semicolon.
    open_ended: bool = False


@dataclass
class ValidationResult:
    diagnostics: list[Diagnostic]
    variables_used: list[str]
    variables_defined: list[str]

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)


class _Lines:
    """Offset -> (line, col) for the original text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer(r"\n", text)]

    def position(self, offset: int) -> tuple[int, int]:
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, offset - self.starts[lo] + 1

    def line_end_col(self, line: int) -> int:
        start = self.starts[line - 1]
        end = self.text.find("\n", start)
        end = len(self.text) if end < 0 else end
        return end - start + 1


def _skip_quoted(text: str, i: int) -> int:
    """Return the index after a quoted/commented region starting at i, or i if none."""
    n = len(text)
    ch = text[i]
    if text.startswith("--", i):
        end = text.find("\n", i)
        return n if end < 0 else end
    if text.startswith("/*", i):
        depth, j = 0, i
        while j < n:
            if text.startswith("/*", j):
                depth += 1
                j += 2
            elif text.startswith("*/", j):
                depth -= 1
                j += 2
                if depth == 0:
                    return j
            else:
                j += 1
        return n
    if ch == "'" or ch == '"':
        escapes = ch == "'" and i > 0 and text[i - 1] in "eE"
        j = i + 1
        while j < n:
            if escapes and text[j] == "\\":
                j += 2
                continue
            if text[j] == ch:
                if j + 1 < n and text[j + 1] == ch:
                    j += 2
                    continue
                return j + 1
            j += 1
        return n
    if ch == "$":
        match = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", text[i:])
        if match:
            tag = match.group(0)
            end = text.find(tag, i + len(tag))
            return n if end < 0 else end + len(tag)
    return i


def split_commands(text: str) -> list[Command]:
    """Split a pgbench script into meta-commands (one per line) and SQL commands (to `;`)."""
    commands: list[Command] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("--", i):
            i = _skip_quoted(text, i)
            continue
        if ch == "\\":
            end = i
            # A trailing backslash continues a meta-command on the next line.
            while True:
                nl = text.find("\n", end)
                if nl < 0:
                    end = n
                    break
                if text[nl - 1] == "\\" and nl - 1 > i:
                    end = nl + 1
                    continue
                end = nl
                break
            raw = text[i:end]
            words = raw[1:].replace("\\\n", " ").split()
            commands.append(
                Command("meta", i, end, raw, words[0] if words else "", words[1:] if words else [])
            )
            i = end
            continue
        # SQL command: up to `;` outside quotes, or up to a following meta-command.
        start, j = i, i
        open_ended = False
        while j < n:
            skipped = _skip_quoted(text, j)
            if skipped != j:
                j = skipped
                continue
            if text[j] == ";":
                j += 1
                break
            if text[j] == "\\":
                open_ended = True
                break
            j += 1
        commands.append(Command("sql", start, j, text[start:j], open_ended=open_ended))
        i = j
    return commands


def _code_mask(sql: str) -> list[bool]:
    """True for characters outside quotes and comments."""
    mask = [True] * len(sql)
    i = 0
    while i < len(sql):
        skipped = _skip_quoted(sql, i)
        if skipped != i:
            for k in range(i, skipped):
                mask[k] = False
            i = skipped
        else:
            i += 1
    return mask


def substitute_variables(sql: str) -> tuple[str, list[tuple[str, int]]]:
    """Replace :name with a same-length literal so parser offsets keep matching the source."""
    mask = _code_mask(sql)
    out = list(sql)
    used: list[tuple[str, int]] = []
    for match in _VAR_RE.finditer(sql):
        start = match.start()
        if not mask[start] or (start > 0 and sql[start - 1] == ":"):
            continue
        if match.end() < len(sql) and sql[match.end()] == ":":
            continue
        used.append((match.group(1), start))
        replacement = "0".ljust(match.end() - start)
        out[start : match.end()] = list(replacement)
    return "".join(out), used


def _suggestion(sql: str, location: int, message: str) -> tuple[str | None, int, int]:
    """Keyword typo hint: checks the reported token and the word before it (FORM -> FROM)."""
    near = _NEAR_RE.search(message)
    candidates: list[tuple[int, str]] = []
    before = [m for m in _WORD_RE.finditer(sql[:location])]
    if before:
        candidates.append((before[-1].start(), before[-1].group(0)))
    if near and near.group(1):
        candidates.append((location, near.group(1)))
    for start, word in reversed(candidates):
        upper = word.upper()
        if upper in SQL_KEYWORDS or not word.isalpha():
            continue
        match = difflib.get_close_matches(upper, SQL_KEYWORDS, n=1, cutoff=0.74)
        if match:
            return match[0], start, start + len(word)
    return None, location, location


def validate_script(
    text: str,
    server_major: int | None = None,
    defined_variables: frozenset[str] = frozenset(),
) -> ValidationResult:
    lines = _Lines(text)
    diagnostics: list[Diagnostic] = []

    def add(
        start: int, end: int, severity: Severity, message: str, rule: str | None = None
    ) -> None:
        line, col = lines.position(start)
        end_line, end_col = lines.position(max(end, start + 1))
        if end_line != line:
            end_col = lines.line_end_col(line)
        diagnostics.append(Diagnostic(line, col, max(end_col, col + 1), severity, message, rule))

    commands = split_commands(text)
    defined: set[str] = set(AUTOMATIC_VARIABLES) | set(defined_variables)
    dynamic_prefixes: list[str] = []
    used: list[tuple[str, int]] = []
    if_stack: list[tuple[Command, bool]] = []  # (command, else seen)
    open_transactions: list[int] = []
    previous: Command | None = None

    for cmd in commands:
        if cmd.kind == "meta":
            _check_meta(cmd, add, if_stack, previous, defined, dynamic_prefixes, used)
        else:
            _check_sql(cmd, text, add, used, open_transactions, server_major)
        previous = cmd

    for cmd, _ in if_stack:
        add(cmd.start, cmd.start + len(cmd.name) + 1, "error", "Незакрытый \\if: нет \\endif")
    for start in open_transactions:
        add(
            start,
            start + 5,
            "warning",
            "BEGIN без END: транзакция не закрыта в сценарии",
            "begin_without_end",
        )

    unknown_seen: set[str] = set()
    for name, offset in used:
        if name in defined or any(name.startswith(p) for p in dynamic_prefixes):
            continue
        add(
            offset,
            offset + len(name) + 1,
            "warning",
            f"Переменная :{name} не задана через \\set — задайте её или передайте через -D",
        )
        unknown_seen.add(name)

    diagnostics.sort(key=lambda d: (d.line, d.col))
    return ValidationResult(
        diagnostics=diagnostics,
        variables_used=sorted({name for name, _ in used}),
        variables_defined=sorted(defined - AUTOMATIC_VARIABLES - set(defined_variables)),
    )


def _check_meta(
    cmd: Command,
    add: _AddFn,
    if_stack: list[tuple[Command, bool]],
    previous: Command | None,
    defined: set[str],
    dynamic_prefixes: list[str],
    used: list[tuple[str, int]],
) -> None:
    name = cmd.name
    name_end = cmd.start + 1 + len(name)
    if name in FORBIDDEN_META:
        add(
            cmd.start,
            name_end,
            "error",
            f"\\{name} запрещён: выполняет команды на машине агента",
            name,
        )
        return
    if name not in META_COMMANDS:
        add(cmd.start, name_end, "error", f"Неизвестная мета-команда \\{name}")
        return
    lo, hi = META_COMMANDS[name]
    if len(cmd.args) < lo or (hi is not None and len(cmd.args) > hi):
        expected = f"{lo}" if hi == lo else f"от {lo}" + (f" до {hi}" if hi is not None else "")
        add(
            cmd.start,
            cmd.end,
            "error",
            f"\\{name}: неверное число аргументов (нужно {expected}, передано {len(cmd.args)})",
        )
        return

    # Variables referenced in meta-command arguments (\set expressions, \sleep, \if).
    arg_text_start = name_end
    for match in _VAR_RE.finditer(cmd.text[len(name) + 1 :]):
        used.append((match.group(1), arg_text_start + match.start()))

    if name == "set":
        if not _IDENT_RE.match(cmd.args[0]):
            add(cmd.start, cmd.end, "error", f"\\set: некорректное имя переменной {cmd.args[0]}")
        else:
            defined.add(cmd.args[0])
    elif name == "sleep":
        value = cmd.args[0]
        if not (value.isdigit() or value.startswith(":")):
            add(cmd.start, cmd.end, "error", "\\sleep: ожидается число или :переменная")
        if len(cmd.args) == 2 and cmd.args[1] not in SLEEP_UNITS:
            add(cmd.start, cmd.end, "error", "\\sleep: единица должна быть us, ms или s")
    elif name == "if":
        if_stack.append((cmd, False))
    elif name in ("elif", "else"):
        if not if_stack:
            add(cmd.start, name_end, "error", f"\\{name} без \\if")
        elif if_stack[-1][1]:
            add(cmd.start, name_end, "error", f"\\{name} после \\else")
        elif name == "else":
            if_stack[-1] = (if_stack[-1][0], True)
    elif name == "endif":
        if not if_stack:
            add(cmd.start, name_end, "error", "\\endif без \\if")
        else:
            if_stack.pop()
    elif name in ("gset", "aset"):
        if previous is None or previous.kind != "sql":
            add(cmd.start, name_end, "error", f"\\{name} должен следовать за SQL-командой")
        else:
            prefix = cmd.args[0] if cmd.args else ""
            columns = _result_columns(previous.text)
            if columns is None:
                dynamic_prefixes.append(prefix)
            else:
                defined.update(prefix + c for c in columns)


def _result_columns(sql: str) -> list[str] | None:
    """Output column names of a SELECT for \\gset; None when they cannot be determined."""
    from pglast import ast

    try:
        stmts = parse_sql(substitute_variables(sql)[0])
    except ParseError:
        return None
    if not stmts or not isinstance(stmts[-1].stmt, ast.SelectStmt):
        return None
    names: list[str] = []
    for target in stmts[-1].stmt.targetList or ():
        if target.name:
            names.append(str(target.name))
        elif isinstance(target.val, ast.ColumnRef) and target.val.fields:
            last = target.val.fields[-1]
            if not isinstance(last, ast.String):
                return None
            names.append(str(last.sval))
        else:
            return None
    return names


def _check_sql(
    cmd: Command,
    text: str,
    add: _AddFn,
    used: list[tuple[str, int]],
    open_transactions: list[int],
    server_major: int | None,
) -> None:
    sql_text = cmd.text
    substituted, variables = substitute_variables(sql_text)
    used.extend((name, cmd.start + offset) for name, offset in variables)
    try:
        statements = parse_sql(substituted)
    except ParseError as exc:
        message = str(exc.args[0]) if exc.args else str(exc)
        reported = exc.args[1] if len(exc.args) > 1 else None
        location = reported if isinstance(reported, int) else 0
        location = min(max(location, 0), max(len(sql_text) - 1, 0))
        hint, start, end = _suggestion(substituted, location, message)
        if hint is None:
            token = _WORD_RE.match(sql_text, location)
            end = token.end() if token else location + 1
        suffix = f" · возможно, имелось в виду {hint}" if hint else ""
        add(cmd.start + start, cmd.start + end, "error", f"{message}{suffix}")
        return

    for raw in statements:
        stmt_start = cmd.start + (raw.stmt_location or 0)
        # Skip leading whitespace/comments so the marker lands on the statement keyword.
        while stmt_start < cmd.end and text[stmt_start].isspace():
            stmt_start += 1
        first_word = _WORD_RE.match(text, stmt_start)
        stmt_end = first_word.end() if first_word else stmt_start + 1

        for finding in safety.check_statement(raw.stmt):
            severity = LEVEL_SEVERITY[finding.level]
            if finding.location is not None:
                start = cmd.start + finding.location
                word = _WORD_RE.match(text, start)
                add(
                    start,
                    word.end() if word else start + 1,
                    severity,
                    finding.message,
                    finding.rule,
                )
            else:
                add(stmt_start, stmt_end, severity, finding.message, finding.rule)

        delta = safety.transaction_delta(raw.stmt)
        if delta > 0:
            open_transactions.append(stmt_start)
        elif delta < 0 and open_transactions:
            open_transactions.pop()

        if server_major is not None:
            for major, feature, node_at in safety.version_requirements(raw.stmt):
                if server_major < major:
                    at = stmt_start if node_at is None else cmd.start + node_at
                    width = stmt_end - stmt_start if node_at is None else len(feature.split()[0])
                    add(
                        at,
                        at + width,
                        "error",
                        f"{feature} не поддерживается в PostgreSQL {server_major} "
                        f"(нужен {major} или новее)",
                        "server_version",
                    )
