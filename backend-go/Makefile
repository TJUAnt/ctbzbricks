.PHONY: fmt fmt-check generate sqlc-vet test test-integration test-performance test-postgres vet check run-api run-worker migrate-help studio-manifest studio-import

fmt:
	gofmt -w $$(find . -name '*.go' -not -path './db/generated/*')

fmt-check:
	@test -z "$$(gofmt -l .)" || (gofmt -l . && exit 1)

generate:
	go tool sqlc generate

sqlc-vet:
	go tool sqlc vet

test:
	go test ./...

test-integration:
	go test -p=1 -tags=integration ./tests/integration/...

test-performance:
	go test -p=1 -tags=integration ./tests/performance/...

test-postgres:
	./scripts/test-postgres.sh

vet:
	go vet ./...

check: fmt-check test vet sqlc-vet

run-api:
	go run ./cmd/api

run-worker:
	go run ./cmd/worker

migrate-help:
	go run ./cmd/migrate --help

studio-manifest:
	@test -n "$(STUDIO_ROOT)" || (echo "STUDIO_ROOT is required"; exit 1)
	@test -n "$(OUT_DIR)" || (echo "OUT_DIR is required"; exit 1)
	go run ./cmd/studio-manifest --studio-root "$(STUDIO_ROOT)" --out-dir "$(OUT_DIR)" $(if $(LEGACY_PARTS_FILE),--legacy-parts-file "$(LEGACY_PARTS_FILE)")

studio-import:
	@test -n "$(MANIFEST)" || (echo "MANIFEST is required"; exit 1)
	go run ./cmd/studio-import --manifest "$(MANIFEST)" --status "$(or $(STATUS),building)" $(if $(LDRAW_ROOT),--ldraw-root "$(LDRAW_ROOT)") $(if $(DATABASE_URL),--database-url "$(DATABASE_URL)") $(if $(CREATED_BY),--created-by "$(CREATED_BY)") $(if $(LIBRARY_ID),--library-id "$(LIBRARY_ID)") $(if $(DRY_RUN),--dry-run) $(if $(LIMIT),--limit "$(LIMIT)")
