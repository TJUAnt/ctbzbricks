#!/bin/sh
set -eu

for command_name in initdb pg_ctl pg_dump curl; do
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
# 隔离库没有恢复价值；关闭持久 WAL 成本，使十万/百万行计划 fixture 不挤占开发机磁盘。
pg_ctl -D "$cluster_dir" -o "-h 127.0.0.1 -p $pg_port -k $socket_dir -c fsync=off -c full_page_writes=off -c wal_level=minimal -c max_wal_senders=0 -c max_wal_size=128MB -c min_wal_size=32MB" -w start >/dev/null

isolated_database_url="postgresql://postgres@127.0.0.1:$pg_port/postgres?sslmode=disable"
export DATABASE_URL="$isolated_database_url"
export TEST_DATABASE_URL="$isolated_database_url"
export APP_ENV=test

go run ./cmd/migrate up
go run ./cmd/migrate down
go run ./cmd/migrate up
go run ./cmd/migrate up
go run ./cmd/migrate version
# 百万级关系计划门禁只在显式开启时输出详细计划，避免日常集成测试产生大量日志。
integration_test_flags=""
if [ "${RUN_PIXEL_PLAN_TEST:-0}" = "1" ] || [ "${RUN_STAR_SIZE_PLAN_TEST:-0}" = "1" ] || [ "${RUN_WATCH_LIST_PLAN_TEST:-0}" = "1" ] || [ "${RUN_WATCH_FEED_PLAN_TEST:-0}" = "1" ] || [ "${RUN_PUBLIC_FEED_PLAN_TEST:-0}" = "1" ] || [ "${RUN_COMPONENT_LIST_PLAN_TEST:-0}" = "1" ] || [ "${RUN_VERSION_PARTS_PLAN_TEST:-0}" = "1" ] || [ "${RUN_PART_SEARCH_PLAN_TEST:-0}" = "1" ]; then
	integration_test_flags="-v"
fi
# 默认执行完整集成集；性能门禁可在低磁盘 CI runner 上显式缩小包集合，迁移和启动无 DDL 契约仍会执行。
integration_packages=${BRICKBUILDER_TEST_PACKAGES:-"./db/generated ./internal/database ./internal/component ./internal/artifact ./internal/task ./internal/worker ./internal/ingestion ./internal/workbench ./internal/httpapi ./internal/partlibrary ./internal/pixel2d"}
go test $integration_test_flags -p=1 -tags=integration $integration_packages

before_schema="$test_root/schema-before.sql"
after_schema="$test_root/schema-after.sql"
# PostgreSQL 17.6 起会生成随机 psql restrict key；仅在本脚本创建的可信隔离库中固定该标记，
# 使启动前后仍逐字比较全部 DDL，不把备份工具的随机控制行误判为运行时 schema 变更。
dump_restrict_flags=""
case "$(pg_dump --help)" in
	*--restrict-key*) dump_restrict_flags="--restrict-key=brickbuilderStartupContract" ;;
esac
pg_dump "$isolated_database_url" $dump_restrict_flags --schema-only --schema=component_repo --schema=pixel_2d --no-owner --no-privileges >"$before_schema"

GO_BACKEND_HOST=127.0.0.1 GO_BACKEND_PORT="$api_port" go run ./cmd/api >"$test_root/api.log" 2>&1 &
api_pid=$!
WORKER_ID=g2-contract-worker WORKER_HEALTH_CHECK_INTERVAL=1s go run ./cmd/worker >"$test_root/worker.log" 2>&1 &
worker_pid=$!

# 启动契约同时验证真实 HTTP server 暴露固定指标，而不只验证内存 Handler。
metrics_output=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
	if metrics_output=$(curl -fs --max-time 2 "http://127.0.0.1:$api_port/metrics"); then
		break
	fi
	sleep 1
done
case "$metrics_output" in
	*'component_domain_event_total{event_type="component.version.published.v1",result="committed"} 0'*) ;;
	*)
		echo "metrics startup contract failed" >&2
		exit 1
		;;
esac
case "$metrics_output" in
	*'component_watch_mutation_total{action="watch",result="succeeded"} 0'*) ;;
	*)
		echo "watch mutation metrics startup contract failed" >&2
		exit 1
		;;
esac
case "$metrics_output" in
	*'component_watch_feed_requests_total{result="succeeded"} 0'*) ;;
	*)
		echo "watch Feed metrics startup contract failed" >&2
		exit 1
		;;
esac
kill "$api_pid" "$worker_pid"
wait "$api_pid" || true
wait "$worker_pid" || true
api_pid=""
worker_pid=""

pg_dump "$isolated_database_url" $dump_restrict_flags --schema-only --schema=component_repo --schema=pixel_2d --no-owner --no-privileges >"$after_schema"
cmp "$before_schema" "$after_schema"

echo "isolated PostgreSQL migration and startup contract: PASS"
