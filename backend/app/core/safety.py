"""Dangerous SQL rules, evaluated on the pglast parse tree (not on text).

Levels follow docs/architecture.md, «Защита тестируемой базы → Сценарии»:
- forbidden: the run is impossible for anyone;
- danger: allowed only after explicit confirmation;
- attention: marked in the editor, no confirmation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pglast import ast
from pglast.enums import ObjectType, TransactionStmtKind

Level = Literal["forbidden", "danger", "attention"]

FORBIDDEN_FUNCTIONS = {"pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf"}
BENCH_TABLE_PREFIX = "pgbench_"

# AST nodes that need a newer server than 13 (the oldest supported version).
MIN_VERSION_NODES: dict[str, tuple[int, str]] = {
    "MergeStmt": (15, "MERGE"),
    "JsonIsPredicate": (16, "IS JSON"),
    "JsonObjectConstructor": (16, "JSON_OBJECT"),
    "JsonArrayConstructor": (16, "JSON_ARRAY"),
    "JsonArrayQueryConstructor": (16, "JSON_ARRAY"),
    "JsonObjectAgg": (16, "JSON_OBJECTAGG"),
    "JsonArrayAgg": (16, "JSON_ARRAYAGG"),
    "JsonTable": (17, "JSON_TABLE"),
    "JsonFuncExpr": (17, "JSON_QUERY / JSON_VALUE / JSON_EXISTS"),
    "JsonParseExpr": (17, "JSON()"),
    "JsonScalarExpr": (17, "JSON_SCALAR"),
    "JsonSerializeExpr": (17, "JSON_SERIALIZE"),
}


@dataclass(frozen=True)
class Finding:
    level: Level
    rule: str
    message: str
    # Offset of the node inside the statement text when pglast knows it.
    location: int | None = None


def walk(node: Any) -> Iterator[ast.Node]:
    if isinstance(node, ast.Node):
        yield node
        for field in node:
            yield from walk(getattr(node, field))
    elif isinstance(node, tuple | list):
        for item in node:
            yield from walk(item)


def _location(node: ast.Node) -> int | None:
    location = getattr(node, "location", None)
    return location if isinstance(location, int) and location >= 0 else None


def _relation_name(relation: Any) -> str | None:
    return relation.relname if isinstance(relation, ast.RangeVar) else None


def _func_name(node: ast.FuncCall) -> str:
    parts = [getattr(p, "sval", "") for p in node.funcname or ()]
    return parts[-1].lower() if parts else ""


def _is_vacuum_full(node: ast.VacuumStmt) -> bool:
    return bool(node.is_vacuumcmd) and any(
        isinstance(opt, ast.DefElem) and opt.defname == "full" for opt in node.options or ()
    )


def check_statement(stmt: ast.Node) -> list[Finding]:
    """Rules for one parsed statement."""
    findings: list[Finding] = []

    def add(level: Level, rule: str, message: str, node: ast.Node | None = None) -> None:
        findings.append(Finding(level, rule, message, _location(node) if node else None))

    for node in walk(stmt):
        match node:
            case ast.DropdbStmt():
                add("forbidden", "drop_database", "DROP DATABASE запрещён")
            case ast.DropRoleStmt():
                add("forbidden", "drop_role", "DROP ROLE запрещён")
            case ast.AlterSystemStmt():
                add("forbidden", "alter_system", "ALTER SYSTEM запрещён")
            case ast.CreateRoleStmt():
                add("forbidden", "create_role", "CREATE ROLE запрещён")
            case ast.AlterRoleStmt() | ast.AlterRoleSetStmt():
                add("forbidden", "alter_role", "ALTER ROLE запрещён")
            case ast.FuncCall() if _func_name(node) in FORBIDDEN_FUNCTIONS:
                add("forbidden", _func_name(node), f"Вызов {_func_name(node)} запрещён", node)
            case ast.CopyStmt(is_program=True):
                add("forbidden", "copy_program", "COPY … TO/FROM PROGRAM запрещён")
            case ast.DropStmt() if node.removeType == ObjectType.OBJECT_TABLE:
                add("danger", "drop_table", "DROP TABLE удалит таблицу")
            case ast.TruncateStmt():
                add("danger", "truncate", "TRUNCATE удалит все строки таблицы")
            case ast.AlterTableStmt():
                add("danger", "alter_table", "ALTER TABLE изменит структуру таблицы")
            case ast.VacuumStmt() if _is_vacuum_full(node):
                add("danger", "vacuum_full", "VACUUM FULL блокирует таблицу и переписывает её")
            case ast.ClusterStmt():
                add("danger", "cluster", "CLUSTER блокирует таблицу и переписывает её")
            case ast.ReindexStmt():
                add("danger", "reindex", "REINDEX блокирует индекс на время перестроения")
            case ast.DeleteStmt() if node.whereClause is None:
                add("danger", "delete_without_where", "DELETE без WHERE удалит все строки")
            case ast.UpdateStmt() if node.whereClause is None:
                add("danger", "update_without_where", "UPDATE без WHERE изменит все строки")
            case ast.LockStmt():
                add("danger", "lock_table", "LOCK TABLE блокирует таблицу")
            case _:
                pass

        if isinstance(node, ast.InsertStmt | ast.UpdateStmt | ast.DeleteStmt | ast.MergeStmt):
            name = _relation_name(node.relation)
            if name is not None and not name.startswith(BENCH_TABLE_PREFIX):
                add(
                    "attention",
                    "write_non_pgbench",
                    f"Запись в таблицу {name}, которая не относится к pgbench_*",
                    node.relation,
                )
    return findings


def transaction_delta(stmt: ast.Node) -> int:
    """+1 for BEGIN/START TRANSACTION, -1 for COMMIT/END/ROLLBACK, 0 otherwise."""
    if not isinstance(stmt, ast.TransactionStmt):
        return 0
    kind = TransactionStmtKind
    if stmt.kind in (kind.TRANS_STMT_BEGIN, kind.TRANS_STMT_START):
        return 1
    if stmt.kind in (kind.TRANS_STMT_COMMIT, kind.TRANS_STMT_ROLLBACK):
        return -1
    return 0


def version_requirements(stmt: ast.Node) -> list[tuple[int, str, int | None]]:
    """(min major version, feature, location) for nodes newer than PostgreSQL 13."""
    found: list[tuple[int, str, int | None]] = []
    for node in walk(stmt):
        requirement = MIN_VERSION_NODES.get(type(node).__name__)
        if requirement is not None:
            found.append((requirement[0], requirement[1], _location(node)))
        if isinstance(node, ast.MergeStmt) and node.returningClause is not None:
            found.append((17, "MERGE … RETURNING", None))
    return found
