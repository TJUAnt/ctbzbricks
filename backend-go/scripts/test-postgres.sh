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
notification_metrics_port=$((58000 + ($$ % 800)))
api_pid=""
worker_pid=""
notification_worker_pid=""

cleanup() {
	if [ -n "$api_pid" ]; then
		kill "$api_pid" 2>/dev/null || true
		wait "$api_pid" 2>/dev/null || true
	fi
	if [ -n "$worker_pid" ]; then
		kill "$worker_pid" 2>/dev/null || true
		wait "$worker_pid" 2>/dev/null || true
	fi
	if [ -n "$notification_worker_pid" ]; then
		kill "$notification_worker_pid" 2>/dev/null || true
		wait "$notification_worker_pid" 2>/dev/null || true
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
go run ./cmd/migrate down
go run ./cmd/migrate up
go run ./cmd/migrate up
go run ./cmd/migrate version
# 百万级关系计划门禁只在显式开启时输出详细计划，避免日常集成测试产生大量日志。
integration_test_flags=""
if [ "${RUN_PIXEL_PLAN_TEST:-0}" = "1" ] || [ "${RUN_STAR_SIZE_PLAN_TEST:-0}" = "1" ] || [ "${RUN_WATCH_LIST_PLAN_TEST:-0}" = "1" ] || [ "${RUN_NOTIFICATION_FANOUT_PLAN_TEST:-0}" = "1" ]; then
	integration_test_flags="-v"
fi
go test $integration_test_flags -p=1 -tags=integration ./internal/database ./internal/component ./internal/artifact ./internal/task ./internal/worker ./internal/notification ./internal/ingestion ./internal/workbench ./internal/httpapi ./internal/partlibrary ./internal/pixel2d

before_schema="$test_root/schema-before.sql"
after_schema="$test_root/schema-after.sql"
pg_dump "$isolated_database_url" --schema-only --schema=component_repo --schema=pixel_2d --no-owner --no-privileges >"$before_schema"

GO_BACKEND_HOST=127.0.0.1 GO_BACKEND_PORT="$api_port" go run ./cmd/api >"$test_root/api.log" 2>&1 &
api_pid=$!
WORKER_ID=g2-contract-worker WORKER_HEALTH_CHECK_INTERVAL=1s go run ./cmd/worker >"$test_root/worker.log" 2>&1 &
worker_pid=$!
NOTIFICATION_WORKER_ID=notification-contract-worker \
	NOTIFICATION_WORKER_METRICS_PORT="$notification_metrics_port" \
	NOTIFICATION_WORKER_METRICS_REFRESH_INTERVAL=1s \
	go run ./cmd/notification-worker >"$test_root/notification-worker.log" 2>&1 &
notification_worker_pid=$!

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
# API 进程保留相同的固定指标契约，但权威 backlog Gauge 由独立 Notification Worker 从 PostgreSQL 采样。
case "$metrics_output" in
	*'component_notification_fanout_total{event_type="component.version.published.v1",result="completed"} 0'*\
*'component_notification_backlog_events 0'*\
*'component_notification_oldest_pending_seconds 0.000000'*) ;;
	*)
		echo "component notification fan-out metrics startup contract failed" >&2
		exit 1
		;;
esac
notification_metrics_output=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
	if notification_metrics_output=$(curl -fs --max-time 2 "http://127.0.0.1:$notification_metrics_port/metrics"); then
		break
	fi
	sleep 1
done
case "$notification_metrics_output" in
	*'component_notification_delivery_attempts_total{result="committed"}'*\
*'component_notification_backlog_events '*\
*'component_notification_unresolved_dead_letters '*) ;;
	*)
		echo "notification worker metrics startup contract failed" >&2
		exit 1
		;;
esac
curl -fs --max-time 2 "http://127.0.0.1:$notification_metrics_port/health/live" >/dev/null
curl -fs --max-time 2 "http://127.0.0.1:$notification_metrics_port/health/ready" >/dev/null

kill "$api_pid" "$worker_pid" "$notification_worker_pid"
wait "$api_pid" || true
wait "$worker_pid" || true
wait "$notification_worker_pid" || true
api_pid=""
worker_pid=""
notification_worker_pid=""

pg_dump "$isolated_database_url" --schema-only --schema=component_repo --schema=pixel_2d --no-owner --no-privileges >"$after_schema"
cmp "$before_schema" "$after_schema"

echo "isolated PostgreSQL migration and startup contract: PASS"
