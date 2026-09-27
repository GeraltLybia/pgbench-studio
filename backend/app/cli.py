"""`studio` command: run the server and emergency maintenance."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import ConfigError, Settings, config_path, load_settings
from app.security.passwords import generate_temporary_password, hash_password
from app.security.sessions import revoke_user_sessions
from app.storage import repo
from app.storage.db import create_engine_for, make_sessionmaker, run_migrations
from app.storage.models import Role


def _load(path: Path | None) -> Settings:
    try:
        return load_settings(path)
    except ConfigError as exc:
        print(f"studio: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from app.logs import configure_logging
    from app.main import create_app

    path = args.config or config_path()
    settings = _load(path)
    try:
        settings.secret_key()
    except ConfigError as exc:
        print(f"studio: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings.logging.level)
    uvicorn.run(
        create_app(settings, path),
        host=settings.server.host,
        port=settings.server.port,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        log_config=None,
        access_log=True,
    )
    return 0


async def reset_admin(settings: Settings, username: str) -> str:
    """Create or restore an admin account with a new temporary password."""
    await asyncio.to_thread(run_migrations, settings.storage.sqlite_path)
    engine = create_engine_for(settings.storage.sqlite_path)
    try:
        async with make_sessionmaker(engine)() as db:
            password = generate_temporary_password()
            user = await repo.get_user_by_username(db, username)
            if user is None:
                await repo.create_user(db, username, password, Role.admin, True)
            else:
                user.role = Role.admin.value
                user.disabled = False
                user.password_hash = hash_password(password)
                user.must_change_password = True
                user.failed_attempts = 0
                user.locked_until = None
                await revoke_user_sessions(db, user.id)
            await db.commit()
            return password
    finally:
        await engine.dispose()


def cmd_reset_admin(args: argparse.Namespace) -> int:
    settings = _load(args.config)
    username = args.username or os.environ.get(settings.auth.admin_user_env)
    if not username:
        print(
            f"studio: укажите --username или переменную {settings.auth.admin_user_env}",
            file=sys.stderr,
        )
        return 2
    password = asyncio.run(reset_admin(settings, username))
    print(f"Администратор {username} восстановлен. Временный пароль: {password}")
    print("При первом входе система потребует сменить пароль.")
    return 0


def cmd_gen_key(_args: argparse.Namespace) -> int:
    print(Fernet.generate_key().decode())
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    from app.main import create_app

    schema = create_app(Settings()).openapi()
    text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio", description="pgbench studio backend")
    parser.add_argument("--config", type=Path, default=None, help="путь к config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="запустить API").set_defaults(func=cmd_serve)
    sub.add_parser("gen-key", help="сгенерировать ключ шифрования").set_defaults(func=cmd_gen_key)
    openapi = sub.add_parser("openapi", help="выгрузить схему OpenAPI")
    openapi.add_argument("-o", "--output", default=None)
    openapi.set_defaults(func=cmd_openapi)

    users = sub.add_parser("users", help="пользователи")
    users_sub = users.add_subparsers(dest="users_command", required=True)
    reset = users_sub.add_parser("reset-admin", help="аварийно восстановить доступ администратора")
    reset.add_argument("--username", default=None)
    reset.set_defaults(func=cmd_reset_admin)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
