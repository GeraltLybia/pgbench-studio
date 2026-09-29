# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ARG PG_MAJOR=18

# The PGDG client package provides libpq and psql; Debian ships pgbench in the server
# package, so only the pgbench binary is extracted from it (the server is not installed).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends "postgresql-client-${PG_MAJOR}" \
 && cd /tmp && apt-get download "postgresql-${PG_MAJOR}" \
 && dpkg-deb -x postgresql-${PG_MAJOR}_*.deb /tmp/pgserver \
 && install -m 0755 "/tmp/pgserver/usr/lib/postgresql/${PG_MAJOR}/bin/pgbench" \
      "/usr/lib/postgresql/${PG_MAJOR}/bin/pgbench" \
 && rm -rf /tmp/pgserver /tmp/*.deb \
 && apt-get purge -y --auto-remove curl gnupg \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV PATH="/app/.venv/bin:/usr/lib/postgresql/${PG_MAJOR}/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PGB_STUDIO_CONFIG=/etc/pgbench-studio/config.yaml

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN uv sync --frozen --no-dev

# Fixed uid and gid: a host directory mounted at /data is prepared with
# `chown 10001:10001` (see README).
RUN groupadd --system --gid 10001 studio \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app studio \
 && install -d -o studio -g studio /data
USER studio
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=4).status != 200)"]

CMD ["studio", "serve"]
