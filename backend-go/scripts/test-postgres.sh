#!/bin/sh
set -eu

for command_name in initdb pg_ctl pg_dump; do
	if ! command -v "$command_name" >/dev/null 2>&1; then
		echo "required PostgreSQL command not found: $command_name" >&2
		exit 1
	fi
done

test_root=$(mktemp -d "${TMPDIR:-/tmp}/brickbuilder-g2.XXXXXX")
cluster_dir="$test_root/data"
socket_dir="$test_root/socket"
pg_port=${BRICKBUILDER_TEST_PG_PORT:-$((55000 + ($$ % 800)))}
api_port=$((57000 + ($$ % 800)))
api_pid=""
worker_pid=""

cleanup() {
	if [ -n "$api_pid" ]; then
		kill "$api_pid" 2>/dev/null || true
		wait "$api_pid" 2>/dev/null || true
	fi
	if [ -n "$worker_pid" ]; then
		kill "$worker_pid" 2>/dev/null || true
		wait "$worker_pid" 2>/dev/null || true
	fi
	if [ -f "$cluster_dir/postmaster.pid" ]; then
		pg_ctl -D "$cluster_dir" -m fast -w stop >/dev/null 2>&1 || true
	fi
	case "$test_root" in
		*/brickbuilder-g2.*) rm -rf -- "$test_root" ;;
		*) echo "refusing to remove unexpected test path: $test_root" >&2 ;;
	esac
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$socket_dir"
initdb -D "$cluster_dir" --username=postgres --auth=trust --no-locale --encoding=UTF8 >/dev/null
pg_ctl -D "$cluster_dir" -o "-h 127.0.0.1 -p $pg_port -k $socket_dir" -w start >/dev/null

isolated_database_url="postgresql://postgres@127.0.0.1:$pg_port/postgres?sslmode=disable"
export DATABASE_URL="$isolated_database_url"
export TEST_DATABASE_URL="$isolated_database_url"
export APP_ENV=test

go run ./cmd/migrate up
go run ./cmd/migrate up
go run ./cmd/migrate version
go test -p=1 -tags=integration ./internal/database ./internal/component ./internal/httpapi

before_schema="$test_root/schema-before.sql"
after_schema="$test_root/schema-after.sql"
pg_dump "$isolated_database_url" --schema-only --schema=component_repo --no-owner --no-privileges >"$before_schema"

GO_BACKEND_HOST=127.0.0.1 GO_BACKEND_PORT="$api_port" go run ./cmd/api >"$test_root/api.log" 2>&1 &
api_pid=$!
WORKER_ID=g2-contract-worker WORKER_HEALTH_CHECK_INTERVAL=1s go run ./cmd/worker >"$test_root/worker.log" 2>&1 &
worker_pid=$!
sleep 2
kill "$api_pid" "$worker_pid"
wait "$api_pid" || true
wait "$worker_pid" || true
api_pid=""
worker_pid=""

pg_dump "$isolated_database_url" --schema-only --schema=component_repo --no-owner --no-privileges >"$after_schema"
cmp "$before_schema" "$after_schema"

echo "isolated PostgreSQL migration and startup contract: PASS"
