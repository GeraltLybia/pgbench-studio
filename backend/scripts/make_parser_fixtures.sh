#!/usr/bin/env bash
# Regenerates tests/fixtures/pgbench/18: real pgbench 18 output against PostgreSQL 13 and 18.
#
# Runs inside the compose backend container (it has pgbench 18 and reaches pg13/pg18):
#   docker compose exec -T -e PGPASSWORD=bench backend bash -s \
#     < backend/scripts/make_parser_fixtures.sh | tar -x -C backend/tests/fixtures/pgbench
#
# Every case directory holds what the runner leaves in a run directory: stdout.log,
# stderr.log, pgbench_log.* and the scripts, plus argv.json and exit_code.
set -u
export PGUSER=bench PGDATABASE=bench PGPORT=5432 LC_ALL=C
OUT=$(mktemp -d)/18
mkdir -p "$OUT"

write_scripts() {
  cat > hot.sql <<'SQL'
\set aid random(1, 100000 * :scale)
\set delta random(-5000, 5000)
UPDATE pgbench_accounts SET abalance = abalance + :delta WHERE aid = :aid;
SELECT abalance FROM pgbench_accounts WHERE aid = :aid;
SQL
  cat > serial.sql <<'SQL'
\set bid 1
BEGIN ISOLATION LEVEL REPEATABLE READ;
UPDATE pgbench_branches SET bbalance = bbalance + 1 WHERE bid = :bid;
END;
SQL
  cat > abort.sql <<'SQL'
\set r random(1, 100)
\if :r > 97
SELECT 1 / 0;
\else
SELECT 1;
\endif
SQL
}

# case name, server host, pgbench arguments...
run_case() {
  local name=$1 host=$2
  shift 2
  local dir="$OUT/$name"
  mkdir -p "$dir"
  (
    cd "$dir" || exit 1
    write_scripts
    if [ -n "${CANCEL_AFTER:-}" ]; then
      # Stop request as the runner sends it: SIGINT.
      PGHOST=$host timeout -s INT "$CANCEL_AFTER" pgbench "$@" > stdout.log 2> stderr.log
    else
      PGHOST=$host pgbench "$@" > stdout.log 2> stderr.log
    fi
    echo $? > exit_code
    python3 -c 'import json, sys; print(json.dumps(["pgbench", *sys.argv[1:]]))' "$@" > argv.json
    for script in *.sql; do
      case " $* " in *" $script@"*) ;; *) rm -f "$script" ;; esac
    done
    # The per-transaction log is gzipped by the runner after parsing; fixtures keep it plain.
  )
}

for host in pg13 pg18; do
  PGHOST=$host pgbench -i -s 1 -q > /dev/null 2>&1
done

AGG=(-P 1 -r -l --log-prefix=pgbench_log --failures-detailed --aggregate-interval=1)
# Failures per second reach the aggregate log only with --failures-detailed.
DETAILED=(-P 1 -r -l --log-prefix=pgbench_log)

for host in pg13 pg18; do
  run_case "mixed-$host" "$host" -c 4 -j 2 -T 5 -M prepared "${AGG[@]}" \
    -b tpcb-like@1 -f hot.sql@3
  run_case "failures-$host" "$host" -c 8 -j 2 -T 3 -M simple "${AGG[@]}" -f serial.sql@1
  run_case "aborted-$host" "$host" -c 4 -j 2 -T 3 -M simple "${AGG[@]}" -f abort.sql@1
done
run_case transactions-pg18 pg18 -c 2 -j 1 -t 300 -M simple "${AGG[@]}" -b select-only@1
run_case rate-pg18 pg18 -c 2 -j 2 -T 3 -M simple -R 200 --latency-limit=5 "${AGG[@]}" \
  -b select-only@1
run_case detailed-pg18 pg18 -c 2 -j 2 -t 400 -M simple "${DETAILED[@]}" -b simple-update@1
run_case detailed-failures-pg13 pg13 -c 6 -j 2 -t 60 -M simple "${DETAILED[@]}" \
  -f serial.sql@1
run_case sampled-pg18 pg18 -c 2 -j 1 -T 2 -M simple "${DETAILED[@]}" --sampling-rate=0.1 \
  -b select-only@1
run_case aborted-detailed-pg18 pg18 -c 4 -j 2 -T 3 -M simple "${DETAILED[@]}" -f abort.sql@1
CANCEL_AFTER=2 run_case cancelled-pg18 pg18 -c 2 -j 2 -T 10 -M simple "${AGG[@]}" \
  -b select-only@1

tar -c -C "$(dirname "$OUT")" 18
